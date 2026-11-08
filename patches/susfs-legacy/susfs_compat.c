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
 * This file brings the two command ids back:
 *
 *  - ADD_SUS_MOUNT flags the target inode with AS_FLAGS_SUS_MOUNT.  The show
 *    helpers in fs/proc_namespace.c then skip every mount whose root is that
 *    inode, which is exactly what susfs v1.x did for a hand-added sus mount
 *    (e.g. "/apex/com.android.art/bin/dex2oat64" that a module bind mounted).
 *    Mounts created by ksu itself are already hidden through their fake
 *    mnt_id, so marking them again is a no-op but keeps the ABI happy.
 *
 *  - ADD_TRY_UMOUNT only acknowledges the request.  Unmounting is handled by
 *    KernelSU's kernel_umount feature and, for ksu mounts, by the fake mnt_id
 *    range, so there is no per-path umount list anymore in v2.x.  Keeping the
 *    call successful is what old detection scripts / modules expect.
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
#include <linux/mount.h>
#include <linux/namei.h>
#include <linux/path.h>
#include <linux/printk.h>
#include <linux/sched.h>
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

#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
extern struct static_key_false susfs_is_hide_sus_mnts_for_non_su_procs_enabled;
#endif

/**
 * susfs_is_sus_mount - check whether a mount was hand-added with add_sus_mount
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

/**
 * susfs_add_sus_mount - CMD_SUSFS_ADD_SUS_MOUNT (0x55560)
 * @user_info: struct st_susfs_sus_mount_legacy __user **
 */
void susfs_add_sus_mount(void __user **user_info)
{
	struct st_susfs_sus_mount_legacy info = {0};
	struct path path;
	struct inode *inode;

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

	info.err = kern_path(info.target_pathname, LOOKUP_FOLLOW, &path);
	if (info.err) {
		SUSFS_COMPAT_LOGE("failed opening file '%s'\n", info.target_pathname);
		goto out_copy_to_user;
	}

	inode = d_backing_inode(path.dentry);
	if (!inode || !inode->i_mapping) {
		SUSFS_COMPAT_LOGE("inode || inode->i_mapping is NULL for '%s'\n",
				  info.target_pathname);
		info.err = -ENOENT;
		goto out_path_put;
	}

	set_bit(AS_FLAGS_SUS_MOUNT, &inode->i_mapping->flags);
	SUSFS_COMPAT_LOGI("flagged AS_FLAGS_SUS_MOUNT on '%s', ino: %lu, dev: %u\n",
			  info.target_pathname, inode->i_ino,
			  inode->i_sb->s_dev);
	info.err = 0;

out_path_put:
	path_put(&path);
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
 * v2.x has no per-path umount list anymore: mounts created by ksu are hidden
 * by their fake mnt_id and removed for app processes by KernelSU's
 * kernel_umount feature.  Accept the call (old modules/scripts call it at boot
 * and treat a failure as fatal) and report success.
 */
void susfs_add_try_umount(void __user **user_info)
{
	struct st_susfs_try_umount_legacy info = {0};

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

#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
	if (!static_branch_likely(&susfs_is_hide_sus_mnts_for_non_su_procs_enabled))
		SUSFS_COMPAT_LOGE("'%s': note, hide_sus_mnts_for_non_su_procs is off; "
				  "run 'ksu_susfs hide_sus_mnts_for_non_su_procs 1' "
				  "if sus mounts must be hidden\n",
				  info.target_pathname);
#endif

	SUSFS_COMPAT_LOGI("'%s' (mnt_mode: %d) accepted; unmounting is handled by "
			  "KernelSU kernel_umount in susfs v2.x\n",
			  info.target_pathname, info.mnt_mode);
	info.err = 0;

out_copy_to_user:
	if (copy_to_user(&((struct st_susfs_try_umount_legacy __user *)*user_info)->err,
			 &info.err, sizeof(info.err)))
		info.err = -EFAULT;

	SUSFS_COMPAT_LOGI("CMD_SUSFS_ADD_TRY_UMOUNT -> ret: %d\n", info.err);
}
