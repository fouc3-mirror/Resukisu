# 发布说明：Android 15 / 6.6 GKI 内核（KernelSU + SUSFS v2.3.0）

## 1. 概览

| 项 | 值 |
|---|---|
| 内核版本 | `6.6.118-android15-8-g0908354dac1b-ab16143355-4k` |
| 构建时间 | `#1 SMP PREEMPT Thu Aug 20 09:40:32 UTC 2026` |
| Root 方案 | 官方 KernelSU（`tiann/KernelSU` main） |
| 隐藏 | SUSFS v2.3.0（SUS_PATH / SUS_MOUNT / SUS_KSTAT / SUS_MAP / OPEN_REDIRECT / SPOOF_UNAME / SPOOF_CMDLINE / AVC log spoofing） |
| 兼容命令 | `add_sus_mount (0x55560)`、`add_try_umount (0x55580)` |
| `/proc/config.gz` | 原厂内容（打包时消毒） |
| BBG 防格机 | 可选，本版开启 |
| ZRAM LZ4KD | 可选，本版关闭 |
| 适用分区 | `boot` = 100,663,296 B（96 MB），A/B |

## 2. 产物与校验

| 文件 | 大小 | SHA256 |
|---|---|---|
| `android15-6.6.118-2026-01-AnyKernel3.zip` | 17.9 MB | `484C4B8E47EEE4F3EBD32D9C61B08A1A729A3EA22AF737F1E2BE40F1171255D1` |
| `android15-6.6.118-2026-01-boot.img` | 100,663,296 B | `4FC33E1BBEC33B71E9B73E0CF0E9E8BAF3573186148A16CF3EBD944F7434884F` |
| `Image`（AK3 内） | 38,046,208 B | — |

boot.img 自检：

```
partition size      : 100663296 (0x6000000)  == boot_a 分区大小
AVB footer          : 位于分区末尾
original_image_size : 38051840
vbmeta_size         : 1472
boot os_version     : 15
boot security_patch : 2026-10-01   （与 ro.build.version.security_patch 一致）
```

## 3. 刷入

```sh
# A) fastboot
fastboot flash boot android15-6.6.118-2026-01-boot.img
fastboot reboot

# B) Recovery / KernelSU 管理器
#    选择 android15-6.6.118-2026-01-AnyKernel3.zip
```

## 4. SUSFS 兼容命令（`0x55560` / `0x55580`）

### 4.1 背景

susfs4ksu 在 v2.2.0 重构 sus_mount：内核改为给 **ksu 进程创建的挂载**自动分配
`mnt_id >= DEFAULT_KSU_MNT_ID (2000000000)`，`fs/proc_namespace.c` 对非 ksu 进程跳过这一段 id。
内核随之把两条命令从分发中删除，只在 `susfs_def.h` 留下 `/* deprecated */`：

| 命令 | 命令号 |
|---|---|
| `ksu_susfs add_sus_mount <path>` | `0x55560` |
| `ksu_susfs add_try_umount <path> <0\|1>` | `0x55580` |

用户态通用二进制（sidex15 `v2.3.0-R28`）仍然保留这两个子命令，调用落到
`ksu_handle_sys_reboot()` 的 `default: return -EINVAL`，`info.err` 保持 255：

```
[-] CMD: '0x55560', SUSFS operation not supported, please enable it in kernel
```

ksu 自己创建的挂载（含 LSPosed 的 dex2oat 绑定）本来就自动隐藏；这两条命令真正服务的是
**手动挂载点**——模块自己 bind mount 出来的路径。

### 4.2 实现

**`add_sus_mount`（0x55560）—— 隐藏**

```
kern_path(path, LOOKUP_FOLLOW)
  → d_backing_inode(path.dentry)
  → set_bit(AS_FLAGS_SUS_MOUNT /* bit 34 */, &inode->i_mapping->flags)
```

`AS_FLAGS_SUS_MOUNT` 是 susfs 保留、v2.3.0 未使用的位，不与 SUS_PATH(33) / SUS_KSTAT(35) /
OPEN_REDIRECT(36) / SUS_MAP(39) 冲突。`fs/proc_namespace.c` 的三个 show 函数据此跳过该挂载，
非 ksu 进程读 `mounts`、`mountinfo`、`mountstats` 时整行消失；标记打在 inode 上，
同一文件的所有 bind mount 一并隐藏。

**`add_try_umount`（0x55580）—— 卸载**

```
1) 标记 inode（立刻从 mountinfo 隐藏）
2) 路径 + mnt_mode 入内核链表
3) ksu_handle_umount()（进程切换到 app uid 时）
     → susfs_legacy_run_try_umount()
     → kern_path() + path_umount()（mnt_mode=1 用 MNT_DETACH）
```

`path_umount()` 会消费 path 引用（`dput()` + `mntput_no_expire()`），代码只在未调用它的分支里
`path_put()`。

### 4.3 ABI 结构体

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

结果通过 `copy_to_user(&info->err, ...)` 写回，旧脚本得到 `rc=0`。

### 4.4 注入点

| 文件 | 改动 |
|---|---|
| `common/fs/Makefile` | `obj-$(CONFIG_KSU_SUSFS_SUS_MOUNT) += susfs_compat.o` |
| `common/fs/proc_namespace.c` | 1 行 extern；3 处 `\|\| susfs_is_sus_mount(mnt)` |
| `KernelSU/kernel/supercall/dispatch.c` | `ksu_handle_sys_reboot()` 补 2 个 `case` |
| `KernelSU/kernel/feature/kernel_umount.c` | `ksu_handle_umount()` 调用 `susfs_legacy_run_try_umount()` |

上游 `fs/susfs.c`、`include/linux/susfs*.h` 未改动。

### 4.5 构建期校验

```
符号 susfs_is_sus_mount 出现次数: 1
符号 susfs_add_sus_mount 出现次数: 2
符号 susfs_add_try_umount 出现次数: 2
符号 susfs_legacy_run_try_umount 出现次数: 2
OK: 0x55560 / 0x55580 的实现已编入内核
```

另有两道断言：`.config` 必须含 `CONFIG_KSU_SUSFS=y` 与 `CONFIG_KSU_SUSFS_SUS_MOUNT=y`；
`Image` 缺任一符号则构建失败。

### 4.6 验收

```sh
# 1) 版本
su -c '/data/adb/ksu/bin/ksu_susfs show version'      # v2.3.0

# 2) 造一个手动挂载点
su -c 'mkdir -p /data/local/tmp/mnt_test && mount --bind /system/bin/true /data/local/tmp/mnt_test'

# 3) 命令可用
su -c '/data/adb/ksu/bin/ksu_susfs add_sus_mount /data/local/tmp/mnt_test; echo rc=$?'   # rc=0

# 4) 隐藏效果
adb shell grep mnt_test /proc/self/mountinfo     # 期望：无输出（非 ksu 视角）
su -c 'grep mnt_test /proc/self/mountinfo'       # 期望：可见（ksu 视角）

# 5) 卸载效果
su -c '/data/adb/ksu/bin/ksu_susfs add_try_umount /data/local/tmp/mnt_test 1; echo rc=$?'
su -c 'am start -n com.android.settings/.Settings'
PID=$(su -c 'pidof com.android.settings')
su -c "grep mnt_test /proc/$PID/mountinfo"       # 期望：无输出

# 6) 日志与清理
dmesg | grep -E 'susfs.*(ADD_SUS_MOUNT|ADD_TRY_UMOUNT|umounting)'
su -c 'umount /data/local/tmp/mnt_test' 2>/dev/null
```

## 5. 给模块作者

可依赖的命令（`ksu_susfs` v2.3.0）：

| 命令 | 作用 |
|---|---|
| `add_sus_path` / `add_sus_path_loop` | 隐藏路径 |
| `add_sus_mount` | 隐藏手动挂载点（非 ksu 进程的 mountinfo 中消失） |
| `add_try_umount` | 在 app 进程命名空间卸载该挂载点 |
| `hide_sus_mnts_for_non_su_procs <0\|1>` | 是否对非 su 进程隐藏 sus 挂载（**需为 1**） |
| `add_sus_kstat` / `update_sus_kstat` / `add_sus_kstat_statically` | kstat 伪装 |
| `add_sus_map` / `add_open_redirect` / `set_uname` / `set_cmdline_or_bootconfig` | 其他隐藏项 |
| `show version` / `show features` | 运行时探测 |

约定：

- 命令通过 `syscall(SYS_reboot, KSU_INSTALL_MAGIC1, SUSFS_MAGIC, cmd, &info)` 下发，
  结果在 `info.err`，`0` 为成功，其余为 errno；
- 调用需要 root；
- `add_try_umount` 的实际卸载依赖 KernelSU 的 `kernel_umount` 特性（默认开启）与模块挂载状态。

不要依赖：

- `/proc/config.gz` 的内容（已替换为原厂内容）；
- 内核日志中的 `susfs:` 输出（`CONFIG_KSU_SUSFS_ENABLE_LOG` 可被关闭）。

## 6. 限制

| 事项 | 说明 |
|---|---|
| 配置依赖 | `CONFIG_KSU_SUSFS=y` + `CONFIG_KSU_SUSFS_SUS_MOUNT=y`（默认开启） |
| 隐藏开关 | 隐藏走 `hide_sus_mnts_for_non_su_procs` 静态键，需为 1 |
| 安全边界 | `add_try_umount` 会真的卸载路径，仅添加自己确认过的挂载点，不要添加 `/system`、`/data` 等核心挂载 |
| 版本适配 | 注入脚本带能力检测；v1.x 分支没有这两个宏时自动跳过，不影响其他 Android 版本构建 |

## 7. 回滚

刷入前用 `dd` 备份原机 `boot_a` 分区（原始转储，不含 userdata）；回滚时刷回该备份：

```sh
fastboot flash boot bak-boot_a.img
```

测试机备份大小（参考）：

```
bak-boot_a.img        100,663,296 B
bak-init_boot_a.img     8,388,608 B
bak-vendor_boot_a.img 100,663,296 B
```

## 8. 发版检查清单

- [x] 注入脚本 + 内核补丁源码已提交
- [x] CI 构建成功，4 个符号均在 `Image` 中
- [x] boot.img 96 MB、AVB footer 在末尾、`15` + `2026-10-01`
- [ ] 真机刷入并跑完 §4.6
- [ ] 发布页附上本文件与两个产物的 sha256
