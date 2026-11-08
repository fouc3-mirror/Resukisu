// SPDX-License-Identifier: GPL-2.0
/*
 * susfs_compat.c - SUSFS v2.x legacy userspace command compatibility
 *
 * susfs4ksu v2.2.0 refactored "sus_mount": instead of the old "add every
 * mount by hand" API, the kernel now assigns a fake mnt_id (>=
 * DEFAULT_KSU_MNT_ID) to every mount that the ksu process creates, and hides
 * that whole id range from non-ksu processes.  The userspace tool (ksu_susfs)
 * however kept the two legacy subcommands, while the 2.3.0 kernel marks their
 * command ids "deprecated" and no longer dispatches them, so both of these
 *
 *     ksu_susfs add_sus_mount  <path>     -> 0x55560
 *     ksu_susfs add_try_umount <path>     -> 0x55580
 *
 * fail with "CMD: '0x55560', SUSFS operation not supported, please enable it
 * in kernel" even though CONFIG_KSU_SUSFS_SUS_MOUNT=y.
 *
 * This file brings both commands back with their v1.x side effects, so that a
 * hand made mount point really disappears from the eyes of non-ksu processes:
 *
 *  - ADD_SUS_MOUNT flags the target inode with AS_FLAGS_SUS_MOUNT.  The show
 *    helpers in fs/proc_namespace.c then skip every mount whose root is that
 *    inode, i.e. the mount no longer shows up in /proc/self/mounts,
 *    /proc/self/mountinfo or /proc/self/mountstats.  This is how v1.x
 *    implemented a hand added sus mount.
 *
 *  - ADD_TRY_UMOUNT remembers the path and really unmounts it inside the mount
 *    namespace of every app process that KernelSU umounts
 *    (susfs_legacy_run_try_umount() is called from ksu_handle_umount()), and
 *    it flags the inode as a sus mount as well, so the entry is hidden even
 *    before the first app is spawned or if the umount fails.
 *
 * Both entry points follow the v2.0.0 (ABI_v2000) struct layout that the
 * current ksu_susfs binary sends, including the trailing "int err" field that
 * carries the result back to userspace.
 */

#include <linux/bitops.h>
#include <linux/cred.h>
#include <linux/dcache.h>
#include <linux/errno.h>
#include <linux/fs.h>
#include <linux/jump_label.h>
#include <linux/list.h>
#include <linux/mount.h>
#include <linux/mutex.h>
#include <linux/namei.h>
#include <linux/path.h>
#include <linux/printk.h>
#include <linux/sched.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/types.h>
#include <linux/uaccess.h>
#include <linux/version.h>

#include <linux/susfs.h>
#include <linux/susfs_def.h>

/*
 * Same logging gate as fs/susfs.c: fs/susfs.c owns the static key, we only
 * read it so that "ksu_susfs enable_log 0" also silences this file.
 */
#if defined(CONFIG_KSU_SUSFS_ENABLE_LOG)
extern struct static_key_true susfs_is_log_enabled;
#define SUSFS_COMPAT_LOGI(fmt, ...)						\
	if (static_branch_likely(&susfs_is_log_enabled))			\
		pr_info("susfs:[%u][%d][%s] " fmt, current_uid().val,		\
			current->pid, __func__, ##__VA_ARGS__)
#define SUSFS_COMPAT_LOGE(fmt, ...)						\
	if (static_branch_likely(&susfs_is_log_enabled))			\
		pr_err("susfs:[%u][%d][%s]" fmt, current_uid().val,		\
			current->pid, __func__, ##__VA_ARGS__)
#else
#define SUSFS_COMPAT_LOGI(fmt, ...) do { } while (0)
#define SUSFS_COMPAT_LOGE(fmt, ...) do { } while (0)
#endif

/* path_umount() lives in fs/namespace.c and is used by KernelSU as well */
extern int path_umount(struct path *path, int flags);

/* owned by fs/susfs.c, we only test it to warn users */
extern struct static_key_false susfs_is_hide_sus_mnts_for_non_su_procs_enabled;

/* ABI_v2000: what the v2.x ksu_susfs binary sends for CMD_SUSFS_ADD_SUS_MOUNT */
struct st_susfs_sus_mount_legacy {
	char target_pathname[SUSFS_MAX_LEN_PATHNAME];
	unsigned long target_dev;
	int err;
};

/* ABI_v2000: what the v2.x ksu_susfs binary sends for CMD_SUSFS_ADD_TRY_UMOUNT */
struct st_susfs_try_umount_legacy {
	char target_pathname[SUSFS_MAX_LEN_PATHNAME];
	int mnt_mode;
	int err;
};

struct susfs_compat_umount_entry {
	struct list_head list;
	char target_pathname[SUSFS_MAX_LEN_PATHNAME];
	int mnt_mode;
};

static LIST_HEAD(LH_LEGACY_TRY_UMOUNT);
static DEFINE_MUTEX(susfs_compat_mutex_try_umount);

/**
 * susfs_is_sus_mount - check whether a mount was hand-added as a sus mount
 * @mnt: mount to inspect
 *
 * Called from the susfs show helpers in fs/proc_namespace.c, which run for
 * every mountinfo/mounts/mountstats line of a non-ksu process.  The flag lives
 * on the inode mapping, so every bind mount of the same file is covered too.
 */
bool susfs_is_sus_mount(struct vfsmount *mnt)
{
	struct inode *inode;

	if (unlikely(!mnt || !mnt->mnt_root))
		return false;

	inode = d_backing_inode(mnt->mnt_root);
	if (unlikely(!inode || !inode->i_mapping))
		return false;

	return test_bit(AS_FLAGS_SUS_MOUNT, &inode->i_mapping->flags);
}

/* flag the inode behind @pathname so its mount entries get hidden */
static int susfs_compat_mark_inode_sus_mount(const char *pathname)
{
	struct path path;
	struct inode *inode;
	int err;

	err = kern_path(pathname, LOOKUP_FOLLOW, &path);
	if (err) {
		SUSFS_COMPAT_LOGE("failed opening file '%s'\n", pathname);
		return err;
	}

	inode = d_backing_inode(path.dentry);
	if (!inode || !inode->i_mapping) {
		SUSFS_COMPAT_LOGE("inode || inode->i_mapping is NULL for '%s'\n",
				  pathname);
		path_put(&path);
		return -ENOENT;
	}

	set_bit(AS_FLAGS_SUS_MOUNT, &inode->i_mapping->flags);
	SUSFS_COMPAT_LOGI("flagged AS_FLAGS_SUS_MOUNT on '%s', ino: %lu, dev: %u\n",
			  pathname, inode->i_ino, inode->i_sb->s_dev);
	path_put(&path);
	return 0;
}

/**
 * susfs_add_sus_mount - CMD_SUSFS_ADD_SUS_MOUNT (0x55560)
 * @user_info: struct st_susfs_sus_mount_legacy __user **
 */
void susfs_add_sus_mount(void __user **user_info)
{
	struct st_susfs_sus_mount_legacy info = {0};

	if (copy_from_user(&info,
			   (struct st_susfs_sus_mount_legacy __user *)*user_info,
			   sizeof(info))) {
		info.err = -EFAULT;
		goto out_copy_to_user;
	}

	/* never trust userspace to terminate the path */
	info.target_pathname[SUSFS_MAX_LEN_PATHNAME - 1] = '\0';

	if (info.target_pathname[0] == '\0') {
		SUSFS_COMPAT_LOGE("target_pathname cannot be empty\n");
		info.err = -EINVAL;
		goto out_copy_to_user;
	}

	info.err = susfs_compat_mark_inode_sus_mount(info.target_pathname);

out_copy_to_user:
	if (copy_to_user(&((struct st_susfs_sus_mount_legacy __user *)*user_info)->err,
			 &info.err, sizeof(info.err)))
		info.err = -EFAULT;

	SUSFS_COMPAT_LOGI("CMD_SUSFS_ADD_SUS_MOUNT -> ret: %d\n", info.err);
}

/**
 * susfs_add_try_umount - CMD_SUSFS_ADD_TRY_UMOUNT (0x55580)
 * @user_info: struct st_susfs_try_umount_legacy __user **
 *
 * Records the path so that susfs_legacy_run_try_umount() really umounts it for
 * every app process KernelSU umounts, and flags the inode as a sus mount so the
 * entry is hidden from mountinfo right away as well.
 */
void susfs_add_try_umount(void __user **user_info)
{
	struct st_susfs_try_umount_legacy info = {0};
	struct susfs_compat_umount_entry *cursor, *entry;

	if (copy_from_user(&info,
			   (struct st_susfs_try_umount_legacy __user *)*user_info,
			   sizeof(info))) {
		info.err = -EFAULT;
		goto out_copy_to_user;
	}

	/* never trust userspace to terminate the path */
	info.target_pathname[SUSFS_MAX_LEN_PATHNAME - 1] = '\0';

	if (info.target_pathname[0] == '\0') {
		SUSFS_COMPAT_LOGE("target_pathname cannot be empty\n");
		info.err = -EINVAL;
		goto out_copy_to_user;
	}

	/* hide the mount entry as well, so this works before any app starts */
	info.err = susfs_compat_mark_inode_sus_mount(info.target_pathname);
	if (info.err)
		goto out_copy_to_user;

	entry = kzalloc(sizeof(*entry), GFP_KERNEL);
	if (!entry) {
		info.err = -ENOMEM;
		goto out_copy_to_user;
	}

	strscpy(entry->target_pathname, info.target_pathname,
		SUSFS_MAX_LEN_PATHNAME - 1);
	entry->mnt_mode = info.mnt_mode;

	mutex_lock(&susfs_compat_mutex_try_umount);
	list_for_each_entry(cursor, &LH_LEGACY_TRY_UMOUNT, list) {
		if (!strcmp(cursor->target_pathname, entry->target_pathname)) {
			mutex_unlock(&susfs_compat_mutex_try_umount);
			kfree(entry);
			SUSFS_COMPAT_LOGI("'%s' is already in the try_umount list\n",
					  info.target_pathname);
			info.err = 0;
			goto out_copy_to_user;
		}
	}
	list_add_tail(&entry->list, &LH_LEGACY_TRY_UMOUNT);
	mutex_unlock(&susfs_compat_mutex_try_umount);

	SUSFS_COMPAT_LOGI("'%s' (mnt_mode: %d) added to try_umount list\n",
			  info.target_pathname, info.mnt_mode);

#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
	if (!static_branch_likely(&susfs_is_hide_sus_mnts_for_non_su_procs_enabled))
		SUSFS_COMPAT_LOGE("note: hide_sus_mnts_for_non_su_procs is off; "
				  "run 'ksu_susfs hide_sus_mnts_for_non_su_procs 1' "
				  "so the entry is hidden from mountinfo too\n");
#endif

out_copy_to_user:
	if (copy_to_user(&((struct st_susfs_try_umount_legacy __user *)*user_info)->err,
			 &info.err, sizeof(info.err)))
		info.err = -EFAULT;

	SUSFS_COMPAT_LOGI("CMD_SUSFS_ADD_TRY_UMOUNT -> ret: %d\n", info.err);
}

/**
 * susfs_legacy_run_try_umount - unmount every path added by add_try_umount
 *
 * Called from KernelSU's ksu_handle_umount(), i.e. in the context of the app
 * process that is being switched to its final uid, with ksu_cred already
 * installed.  Same shape as KernelSU's own try_umount() loop: only unmount
 * paths that are the root of a mount.
 */
void susfs_legacy_run_try_umount(void)
{
	struct susfs_compat_umount_entry *entry;
	struct path path;
	int flags, err;

	if (list_empty(&LH_LEGACY_TRY_UMOUNT))
		return;

	mutex_lock(&susfs_compat_mutex_try_umount);
	list_for_each_entry(entry, &LH_LEGACY_TRY_UMOUNT, list) {
		err = kern_path(entry->target_pathname, 0, &path);
		if (err) {
			SUSFS_COMPAT_LOGE("kern_path('%s') failed: %d\n",
					  entry->target_pathname, err);
			continue;
		}

		/* not the root of a mount (already gone / not a mount point) */
		if (path.dentry != path.mnt->mnt_root) {
			path_put(&path);
			continue;
		}

		flags = (entry->mnt_mode == TRY_UMOUNT_DETACH) ? MNT_DETACH : 0;
		SUSFS_COMPAT_LOGI("umounting '%s' (flags: 0x%x)\n",
				  entry->target_pathname, flags);
		/* path_umount() consumes the path reference */
		err = path_umount(&path, flags);
		if (err)
			SUSFS_COMPAT_LOGE("umount '%s' failed: %d\n",
					  entry->target_pathname, err);
	}
	mutex_unlock(&susfs_compat_mutex_try_umount);
}
