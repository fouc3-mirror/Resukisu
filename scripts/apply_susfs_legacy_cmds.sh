#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 恢复 susfs v2.3.0 内核里被标记 "deprecated" 的两条用户态命令
#
#   CMD_SUSFS_ADD_SUS_MOUNT   0x55560   -> fs/susfs_compat.c + proc_namespace 钩子
#   CMD_SUSFS_ADD_TRY_UMOUNT  0x55580   -> fs/susfs_compat.c（ABI 兼容）
#
# 上游 susfs4ksu v2.2.0 重构了 sus_mount：内核改为给 ksu 进程创建的挂载自动
# 分配 >= DEFAULT_KSU_MNT_ID 的假 mnt_id 来隐藏，于是把 add_sus_mount /
# add_try_umount 从命令分发里删掉了；但用户态 ksu_susfs（含 sidex15 的
# v2.3.0-R28 通用二进制）仍然保留了这两个子命令，调用就返回
#   "CMD: '0x55560', SUSFS operation not supported"
#
# 本脚本在内核源码里补回这两条命令的实现与分发。
# 用法: apply_susfs_legacy_cmds.sh <KERNEL_ROOT>
# ---------------------------------------------------------------------------
set -euo pipefail

KERNEL_ROOT="${1:?usage: $0 <KERNEL_ROOT>}"
COMMON="$KERNEL_ROOT/common"
KSU="$KERNEL_ROOT/KernelSU"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/../patches/susfs-legacy/susfs_compat.c"

log() { printf '[susfs-legacy] %s\n' "$*"; }
die() { printf '[susfs-legacy][error] %s\n' "$*" >&2; exit 1; }

[ -f "$SRC" ] || die "找不到 $SRC"
[ -f "$COMMON/fs/susfs.c" ] || die "找不到 $COMMON/fs/susfs.c —— SUSFS 主补丁没有打上？"
[ -f "$COMMON/fs/proc_namespace.c" ] || die "找不到 fs/proc_namespace.c"
[ -f "$KSU/kernel/supercall/dispatch.c" ] || die "找不到 KernelSU dispatch.c"

mark_disabled() {
    if [ -n "${GITHUB_ENV:-}" ]; then
        echo "SUSFS_LEGACY_COMPAT=0" >> "$GITHUB_ENV"
    fi
}

# 能力检测：只有 susfs v2.x（带 0x55560 定义 + AS_FLAGS_SUS_MOUNT 位）才适用。
# 老分支（v1.x）用 INODE_STATE_* 来标记，那里本来就能处理这两条命令，直接跳过。
DEF="$COMMON/include/linux/susfs_def.h"
if ! grep -q 'define CMD_SUSFS_ADD_SUS_MOUNT' "$DEF" 2>/dev/null || \
   ! grep -q 'define AS_FLAGS_SUS_MOUNT' "$DEF" 2>/dev/null; then
    log "当前 SUSFS 版本没有 0x55560 / AS_FLAGS_SUS_MOUNT，跳过兼容补丁"
    mark_disabled
    exit 0
fi

# --- 1. 源码：fs/susfs_compat.c 并挂进 fs/Makefile -------------------------
cp "$SRC" "$COMMON/fs/susfs_compat.c"
if ! grep -q 'susfs_compat\.o' "$COMMON/fs/Makefile"; then
    printf 'obj-$(CONFIG_KSU_SUSFS_SUS_MOUNT) += susfs_compat.o\n' >> "$COMMON/fs/Makefile"
fi
log "fs/susfs_compat.c 已安装"

# --- 2. proc_namespace.c：隐藏被标记的挂载项 -------------------------------
PN="$COMMON/fs/proc_namespace.c"
if ! grep -q 'susfs_is_sus_mount' "$PN"; then
    sed -i '/extern struct static_key_false susfs_is_hide_sus_mnts_for_non_su_procs_enabled;/a extern bool susfs_is_sus_mount(struct vfsmount *mnt);' "$PN"
fi
# 三个 susfs_show_* 里的跳过判断：mnt_id 在 ksu 区间 或 inode 被打上标记
sed -i 's/if (r->mnt_id >= DEFAULT_KSU_MNT_ID)/if (r->mnt_id >= DEFAULT_KSU_MNT_ID || susfs_is_sus_mount(mnt))/g' "$PN"
hooks=$(grep -c 'susfs_is_sus_mount(mnt)' "$PN" || true)
[ "$hooks" -ge 3 ] || die "proc_namespace.c 钩子数量异常: $hooks（期望 3）"
log "proc_namespace.c 钩子数量: $hooks"

# 视口判定：把 "仅 ksu domain 免过滤" 换成显式规则
# （root 与 ksu domain 看全部；其余一律过滤，含 isolated/sandboxed uid 90000-99999）
if ! grep -q 'susfs_hide_sus_mnts_for_current' "$PN"; then
    sed -i '/extern bool susfs_is_sus_mount(struct vfsmount \*mnt);/a extern bool susfs_hide_sus_mnts_for_current(void);' "$PN"
fi
sed -i 's/if (likely(!susfs_is_current_ksu_domain()))/if (likely(susfs_hide_sus_mnts_for_current()))/g' "$PN"
gate=$(grep -c 'if (likely(susfs_hide_sus_mnts_for_current()))' "$PN" || true)
[ "$gate" -ge 3 ] || die "proc_namespace.c 视口判定补丁失败: $gate（期望 3）"
log "proc_namespace.c 视口判定已改为 susfs_hide_sus_mnts_for_current(): $gate 处"

# --- 3. KernelSU 命令分发：补回 0x55560 / 0x55580 -------------------------
python3 - "$KSU/kernel/supercall/dispatch.c" <<'PY'
import sys
import pathlib

path = pathlib.Path(sys.argv[1])
src = path.read_text()

if "CMD_SUSFS_ADD_SUS_MOUNT" in src:
    print("[susfs-legacy] dispatch.c 已包含兼容命令，跳过")
    sys.exit(0)

anchor = "susfs_set_hide_sus_mnts_for_non_su_procs(arg);"
if src.count(anchor) != 1:
    sys.exit("[susfs-legacy][error] 在 dispatch.c 中没能唯一定位 susfs 分发锚点")

idx = src.index(anchor)
end = src.index("\n", idx) + 1
ret = "                return 0;\n"
if not src.startswith(ret, end):
    sys.exit("[susfs-legacy][error] susfs 分发锚点后不是 return 0;，需要人工检查")

block = (
    "            case CMD_SUSFS_ADD_SUS_MOUNT: {\n"
    "                extern void susfs_add_sus_mount(void __user **user_info);\n"
    "                susfs_add_sus_mount(arg);\n"
    "                return 0;\n"
    "            }\n"
    "            case CMD_SUSFS_ADD_TRY_UMOUNT: {\n"
    "                extern void susfs_add_try_umount(void __user **user_info);\n"
    "                susfs_add_try_umount(arg);\n"
    "                return 0;\n"
    "            }\n"
)
end += len(ret)
path.write_text(src[:end] + block + src[end:])
print("[susfs-legacy] dispatch.c 已补回 CMD_SUSFS_ADD_SUS_MOUNT / CMD_SUSFS_ADD_TRY_UMOUNT")
PY

grep -q 'CMD_SUSFS_ADD_SUS_MOUNT' "$KSU/kernel/supercall/dispatch.c" || die "dispatch.c 补丁失败"
grep -q 'CMD_SUSFS_ADD_TRY_UMOUNT' "$KSU/kernel/supercall/dispatch.c" || die "dispatch.c 补丁失败"
grep -q 'CONFIG_KSU_SUSFS_SUS_MOUNT' "$COMMON/fs/susfs_compat.c" || die "susfs_compat.c 缺少配置守卫"

# --- 4. ksu_handle_umount：真正把 try_umount 的路径卸载掉 -------------------
KU="$KSU/kernel/feature/kernel_umount.c"
[ -f "$KU" ] || die "找不到 $KU"
python3 - "$KU" <<'PY'
import sys
import pathlib

path = pathlib.Path(sys.argv[1])
src = path.read_text()

if "susfs_legacy_run_try_umount" in src:
    print("[susfs-legacy] kernel_umount.c 已包含 try_umount 钩子，跳过")
    sys.exit(0)

anchor = "    revert_creds(saved);\n"
if src.count(anchor) != 1:
    sys.exit("[susfs-legacy][error] kernel_umount.c 中没能唯一定位 revert_creds(saved);")

block = (
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "    {\n"
    "        /* susfs legacy CMD_SUSFS_ADD_TRY_UMOUNT list */\n"
    "        extern void susfs_legacy_run_try_umount(void);\n"
    "        susfs_legacy_run_try_umount();\n"
    "    }\n"
    "#endif\n"
    "\n"
)
path.write_text(src.replace(anchor, block + anchor))
print("[susfs-legacy] kernel_umount.c 已接上 susfs_legacy_run_try_umount()")
PY
grep -q 'susfs_legacy_run_try_umount' "$KU" || die "kernel_umount.c 钩子失败"

if [ -n "${GITHUB_ENV:-}" ]; then
    echo "SUSFS_LEGACY_COMPAT=1" >> "$GITHUB_ENV"
fi

log "SUSFS 兼容命令已就绪 (0x55560 隐藏挂载 / 0x55580 记录并卸载)"
