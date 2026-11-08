# 发布说明：SUSFS v2.x 兼容命令补丁（`0x55560` / `0x55580`）

> 适用：本仓库构建的 **Android 15 / 6.6** GKI 内核（KernelSU + SUSFS v2.3.0）
> 目的：让 `ksu_susfs add_sus_mount` / `add_try_umount` 恢复可用，并且**真的隐藏/卸载**手动挂载点，
> 而不是只返回 `rc=0`。

---

## 1. 背景（为什么需要这个补丁）

susfs4ksu 在 **v2.2.0 重构 sus_mount**：不再由用户态逐条上报挂载，改为内核给 **ksu 进程创建的挂载**
自动分配 `mnt_id >= DEFAULT_KSU_MNT_ID (2000000000)`，`fs/proc_namespace.c` 对非 ksu 进程直接跳过这一段 id。

于是内核把两条命令从分发里删掉，只在 `susfs_def.h` 留下 `/* deprecated */`：

| 命令 | 命令号 |
|---|---|
| `ksu_susfs add_sus_mount <path>` | `0x55560` |
| `ksu_susfs add_try_umount <path> <0\|1>` | `0x55580` |

但用户态通用二进制（sidex15 `v2.3.0-R28` 的 `ksu_susfs`）**仍然保留**这两个子命令。
调用时命令落到 `ksu_handle_sys_reboot()` 的 `default: return -EINVAL`，`info.err` 保持 255
（`ERR_CMD_NOT_SUPPORTED`），用户看到：

```
[-] CMD: '0x55560', SUSFS operation not supported, please enable it in kernel
```

而 `CONFIG_KSU_SUSFS_SUS_MOUNT=y` 明明是开着的。

**对 ksu 自己创建的挂载**（含 LSPosed 的 dex2oat 绑定）其实早已自动隐藏，这两条命令只是 ABI 缺失；
**真正需要它们的是“手动挂载点”**——模块自己 bind mount 出来的路径，必须显式加入 sus 列表才会被隐藏。

---

## 2. 发布产物

| 项 | 值 |
|---|---|
| 内核 release | `6.6.118-android15-8-g0908354dac1b-ab16143355-4k` |
| 构建时间戳 | `#1 SMP PREEMPT Thu Aug 20 09:40:32 UTC 2026` |
| 仓库提交 | `ae9d27b`（工作流 run `42459931543`） |
| AnyKernel3 | `android15-6.6.118-2026-01-AnyKernel3.zip`（17.9 MB）<br>`sha256 484C4B8E47EEE4F3EBD32D9C61B08A1A729A3EA22AF737F1E2BE40F1171255D1` |
| boot.img | `android15-6.6.118-2026-01-boot.img`（100,663,296 B = 96 MB）<br>`sha256 4FC33E1BBEC33B71E9B73E0CF0E9E8BAF3573186148A16CF3EBD944F7434884F` |
| `Image` | 38,046,208 B（AK3 内） |

boot.img 自检（AVB）：

```
partition size      : 100663296 (0x6000000)  == boot_a 分区大小
AVB footer          : 位于分区末尾
original_image_size : 38051840
vbmeta_size         : 1472
boot os_version     : 15
boot security_patch : 2026-10-01   （与 ro.build.version.security_patch 对齐）
```

---

## 3. 工作流结构

### 3.1 入口

| 工作流 | 作用 |
|---|---|
| `.github/workflows/build-ak3-stealth.yml` | 对外入口：10 个 `workflow_dispatch` 输入 → 预检 → 调 `build.yml` → 打包 AK3 |
| `.github/workflows/build.yml` | 实际编译（可复用 workflow，也被 `kernel-a15-6-6.yml` 等调用） |

`build-ak3-stealth.yml` 的输入：

| 输入 | 默认 | 本次使用 |
|---|---|---|
| `android_version` | `android15` | `android15` |
| `kernel_version` | `6.6` | `6.6` |
| `sub_level` | `118` | `118` |
| `os_patch_level` | `2026-01` | `2026-01` |
| `build_time` | `Thu Aug 20 09:40:32 UTC 2026` | 同左 |
| `kernel_localversion` | `-g0908354dac1b-ab16143355-4k` | 同左 |
| `use_zram` | `false` | `false` |
| `use_bbg` | `true` | `true` |
| `revision` | 空 | 空 |
| `boot_security_patch` | `2026-10-01` | `2026-10-01` |

### 3.2 本次新增的三个环节（都在 `build.yml`）

1. **`应用 SUSFS 补丁` 末尾**：调用 `scripts/apply_susfs_legacy_cmds.sh`（注入兼容命令）
2. **`添加 SUSFS 配置` 末尾**：断言 `.config` 里真的有
   `CONFIG_KSU_SUSFS=y` 与 `CONFIG_KSU_SUSFS_SUS_MOUNT=y`
3. **新步骤 `校验 SUSFS 兼容命令已编入内核`**（`准备 Boot 镜像` 之后）：在 `Image` 里
   `strings` 校验 4 个符号，缺一个就 fail —— 防止“代码被 `#ifdef` 掉但构建仍成功”

---

## 4. 代码清单

### 4.1 新增文件

| 文件 | 行数 | 说明 |
|---|---|---|
| `patches/susfs-legacy/susfs_compat.c` | 310 | 两个命令的内核实现（编译到 `common/fs/susfs_compat.o`） |
| `scripts/apply_susfs_legacy_cmds.sh` | 147 | 构建期注入补丁（幂等、带能力检测） |
| `docs/release-susfs-legacy.md` | 本文 | 发布说明 |

### 4.2 修改文件

| 文件 | 增量 | 内容 |
|---|---|---|
| `.github/workflows/build.yml` | +32 行 | 调用注入脚本、`.config` 断言、符号校验步骤 |
| `docs/detection-hardening.md` | +62 行 | §7 记录现象/根因/修复 |

### 4.3 注入点（对上游源码的改动，共 4 处）

| 文件 | 改动 |
|---|---|
| `common/fs/Makefile` | 追加 `obj-$(CONFIG_KSU_SUSFS_SUS_MOUNT) += susfs_compat.o` |
| `common/fs/proc_namespace.c` | 加 1 行 `extern bool susfs_is_sus_mount(struct vfsmount *mnt);`；3 个 show 函数里 `if (r->mnt_id >= DEFAULT_KSU_MNT_ID)` → `\|\| susfs_is_sus_mount(mnt)` |
| `KernelSU/kernel/supercall/dispatch.c` | `ksu_handle_sys_reboot()` 的 switch 里补 2 个 `case`（0x55560 / 0x55580） |
| `KernelSU/kernel/feature/kernel_umount.c` | `ksu_handle_umount()` 中 `revert_creds()` 之前调用 `susfs_legacy_run_try_umount()` |

> 上游 `fs/susfs.c`、`include/linux/susfs*.h` 一行未改，全部是增量文件/增量 hunk。

---

## 5. 实现细节

### 5.1 ABI 结构体（对齐 userspace `ABI_v2000`）

```c
struct st_susfs_sus_mount_legacy {          /* 0x55560 */
    char          target_pathname[256];
    unsigned long target_dev;
    int           err;
};

struct st_susfs_try_umount_legacy {         /* 0x55580 */
    char          target_pathname[256];
    int           mnt_mode;
    int           err;
};
```

结果通过 `copy_to_user(&info->err, ...)` 写回，所以旧脚本/模块拿到 `rc=0`。

### 5.2 `add_sus_mount`（0x55560）—— 真正隐藏

```
kern_path(path, LOOKUP_FOLLOW)
  → d_backing_inode(path.dentry)
  → set_bit(AS_FLAGS_SUS_MOUNT /* bit 34 */, &inode->i_mapping->flags)
```

`AS_FLAGS_SUS_MOUNT` 是 susfs 自己保留、v2.3.0 里**未被使用**的位（bit 34），因此不会与
SUS_PATH(33) / SUS_KSTAT(35) / OPEN_REDIRECT(36) / SUS_MAP(39) 冲突。

`fs/proc_namespace.c` 的三个 show 函数据此跳过该挂载 → 非 ksu 进程读
`/proc/self/mounts`、`/proc/self/mountinfo`、`/proc/self/mountstats` 时**整行消失**。
因为是打在 inode 上，同一文件的所有 bind mount 一起隐藏。

### 5.3 `add_try_umount`（0x55580）—— 真正卸载 + 立即隐藏

```
1) susfs_compat_mark_inode_sus_mount(path)      # 立刻从 mountinfo 隐掉（双保险）
2) 路径 + mnt_mode 存入 LH_LEGACY_TRY_UMOUNT
3) ksu_handle_umount()（每个切到 app uid 的进程）
     → susfs_legacy_run_try_umount()
     → kern_path() + path_umount()
       mnt_mode == 1 (TRY_UMOUNT_DETACH) → MNT_DETACH
```

注意：AOSP `android15-6.6` 的 `path_umount()` 是**消费 path 引用**的
（末尾 `dput()` + `mntput_no_expire()`），所以代码只在“未调用 `path_umount` 就返回”的分支里
`path_put()`，避免 double free。

### 5.4 注入脚本的健壮性

- **能力检测**：`susfs_def.h` 里没有 `CMD_SUSFS_ADD_SUS_MOUNT` 或 `AS_FLAGS_SUS_MOUNT`
  → 判定为老分支，打印后直接跳过（并写 `SUSFS_LEGACY_COMPAT=0` 给后续步骤）；
- **幂等**：重复执行不会重复插 `case` / 钩子（先 grep 再改）；
- **锚点校验**：`sed` 后断言 `proc_namespace.c` 钩子数 ≥ 3；Python 插入前断言锚点唯一；
- **构建期自证**：任一断言失败即让该 step 失败，不会“静默产出没有补丁的内核”。

---

## 6. CI 内已完成的验证

`校验 SUSFS 兼容命令已编入内核` 步骤输出：

```
符号 susfs_is_sus_mount 出现次数: 1
符号 susfs_add_sus_mount 出现次数: 2
符号 susfs_add_try_umount 出现次数: 2
符号 susfs_legacy_run_try_umount 出现次数: 2
OK: 0x55560 / 0x55580 的实现已编入内核
```

注入脚本输出：

```
[susfs-legacy] fs/susfs_compat.c 已安装
[susfs-legacy] proc_namespace.c 钩子数量: 3
[susfs-legacy] dispatch.c 已补回 CMD_SUSFS_ADD_SUS_MOUNT / CMD_SUSFS_ADD_TRY_UMOUNT
[susfs-legacy] kernel_umount.c 已接上 susfs_legacy_run_try_umount()
[susfs-legacy] SUSFS 兼容命令已就绪 (0x55560 隐藏挂载 / 0x55580 记录并卸载)
```

---

## 7. 刷入与验收

### 7.1 刷入

```sh
# A) fastboot（推荐，boot.img 已按 96MB 分区对齐 + AVB 签名）
fastboot flash boot android15-6.6.118-2026-01-boot.img
fastboot reboot

# B) Recovery / KernelSU 管理器刷 AK3
#    选择 android15-6.6.118-2026-01-AnyKernel3.zip
```

### 7.2 验收（重点：看效果，不看 rc）

```sh
# 1) 版本
su -c '/data/adb/ksu/bin/ksu_susfs show version'      # v2.3.0

# 2) 造一个手动挂载点
su -c 'mkdir -p /data/local/tmp/mnt_test && mount --bind /system/bin/true /data/local/tmp/mnt_test'

# 3) 命令可用（原来这里报 0x55560 not supported）
su -c '/data/adb/ksu/bin/ksu_susfs add_sus_mount /data/local/tmp/mnt_test; echo rc=$?'   # rc=0

# 4) 真实生效
adb shell grep mnt_test /proc/self/mountinfo     # 期望：无输出（uid 2000 / 非 ksu 视角）
su -c 'grep mnt_test /proc/self/mountinfo'       # 期望：可见（ksu 视角，设计如此）

# 5) try_umount 真卸载
su -c '/data/adb/ksu/bin/ksu_susfs add_try_umount /data/local/tmp/mnt_test 1; echo rc=$?'
su -c 'am start -n com.android.settings/.Settings'          # 触发 app spawn
PID=$(su -c 'pidof com.android.settings')
su -c "grep mnt_test /proc/$PID/mountinfo"       # 期望：无输出

# 6) 内核日志
dmesg | grep -E 'susfs.*(ADD_SUS_MOUNT|ADD_TRY_UMOUNT|umounting)'

# 7) 清理
su -c 'umount /data/local/tmp/mnt_test' 2>/dev/null
```

---

## 8. 限制与注意事项

| 事项 | 说明 |
|---|---|
| 配置依赖 | 需要 `CONFIG_KSU_SUSFS=y` + `CONFIG_KSU_SUSFS_SUS_MOUNT=y`（本仓库 defconfig 默认已开） |
| 隐藏开关 | 隐藏走的是 susfs 的 `hide_sus_mnts_for_non_su_procs` 静态键，**必须为 1**；`susfs4ksu` 模块开机脚本默认会开，可用 `ksu_susfs hide_sus_mnts_for_non_su_procs 1` 确认 |
| try_umount 生效条件 | 卸载发生在 `ksu_handle_umount()`，即需要 KernelSU 的 `kernel_umount` 特性开启（默认开）且模块已挂载 |
| 老分支 | v1.x susfs 分支本来就有这两条命令，脚本检测到后自动跳过，不影响 a12/a13/a14 构建 |
| 与自动隐藏的关系 | ksu 自己创建的挂载仍走 `mnt_id >= 2000000000` 自动隐藏，本补丁不改变该路径，两者互不冲突 |
| 安全边界 | `add_try_umount` 会真的卸载路径，**只加自己确认过的挂载点**，不要加 `/system`、`/data` 这类核心挂载 |

---

## 9. 回滚

```sh
# 刷回原厂/上一版 boot
fastboot flash boot device-backup/bak-boot_a.img
```

分区备份（dd 原始转储，未做任何 userdata 操作）：

```
device-backup/bak-boot_a.img        100,663,296 B
device-backup/bak-init_boot_a.img     8,388,608 B
device-backup/bak-vendor_boot_a.img 100,663,296 B
```

---

## 10. 发版检查清单

- [x] `patches/susfs-legacy/susfs_compat.c` 已提交
- [x] `scripts/apply_susfs_legacy_cmds.sh` 已提交
- [x] `build.yml` 注入 + `.config` 断言 + 符号校验
- [x] CI 构建成功，4 个符号全部在 `Image` 中
- [x] boot.img 96 MB / AVB footer 在末尾 / `15` + `2026-10-01`
- [ ] 真机刷入并跑完 §7.2 的 1–6 步（发布前补）
- [ ] 发布页附上本文件与两个产物的 sha256
