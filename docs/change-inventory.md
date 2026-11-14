# 相对上游的改动说明

## 0. 范围

对比基准：`haidayne/Resukisu` 的 `dev` 分支 `36309b1`（2026-03-10）。
本文只按主题说明**改了什么、为什么改**；逐条提交请看仓库的 commits 页面。

```
27 files changed, 5511 insertions(+), 974 deletions(-)
```

## 1. 一句话

把构建链从 **SUKISU** 换成 **官方 KernelSU + 官方 AnyKernel3**，SUSFS 跟随上游 v2.x（当前 v2.4.0），
叠加一层反检测加固（`/proc/config.gz` 消毒、日志/符号处理、LTO 与 LOCALVERSION 对齐原厂），
并补回 SUSFS v2.x 被删除的 `add_sus_mount` / `add_try_umount` 两条命令。

---

## 2. 构建主链：`.github/workflows/build.yml`

| 区块 | 改动 |
|---|---|
| KernelSU | 改用官方 `tiann/KernelSU`（`setup.sh` + `KSU_REF`），移除 SukiSU 分支逻辑、KPM、SukiSU 专属挂载；`ksu_ref` 可锁 tag/commit，上游与 SUSFS 不兼容时临时固定 |
| AnyKernel3 | 使用 `WildKernels/AnyKernel3@gki-2.0`；若检测到上游示例 `anykernel.sh`（`device.name1=maguro`）则替换为 GKI 安全模板（`BLOCK=auto`、`IS_SLOT_DEVICE=auto`、`split_boot`），并加 GKI 内核版本闸门 |
| SUSFS | 分支由 `gki-<android>-<kernel>` 决定；主补丁 + `KernelSU/10_enable_susfs_for_ksu.patch`；KSU 侧补丁应用后若有 `.rej` 直接报错（不再静默容错）；WildKernels 兼容补丁缺失时跳过而不是失败 |
| 内核配置 | `CONFIG_KSU_SUSFS*` 10 项写入 defconfig；`CONFIG_BBG` 可选；ZRAM LZ4KD 可选；`CONFIG_KVM` 可选（`use_kvm`，默认开）；关闭 `check_defconfig` |
| 隐身 | `CONFIG_LOCALVERSION` 可控并回读校验；LTO 可指定（`auto`/`thin`/`none`）；可关闭 `CONFIG_KSU_SUSFS_ENABLE_LOG`（并补 `SUSFS_LOGI_RL` 空实现）；`/proc/config.gz` 内容替换为原厂内容 |
| 时间戳 | `KBUILD_BUILD_TIMESTAMP` + 改写 `scripts/mkcompile_h` 的 `UTS_VERSION`，输出 `#1 SMP PREEMPT <指定时间>` |
| boot.img | header v4；`--os_version` / `--os_patch_level`；写入 AVB 属性 `com.android.build.boot.os_version`、`…security_patch`；`--partition_size` 取仓库变量 `BOOT_PARTITION_SIZE`；构建后校验产物尺寸等于分区大小 |

## 3. 打包入口（3 个 workflow）

| 文件 | 用途 | 关键输入 |
|---|---|---|
| `build-ak3.yml` | 单版本 AK3 打包（标准版） | android / kernel / sub_level / os_patch_level / revision / build_time / kernel_localversion / use_zram / use_bbg / use_kvm / ksu_ref |
| `build-ak3-stealth.yml` | 隐身版 AK3（`sanitize_config=true`） | 上述 + `boot_security_patch` |
| `build-ak3-toggle.yml` | 开关版：4 个布尔量组合，用于二分排查反检测项 | hide_kernel_config / use_bbg / disable_susfs_log / lto / use_kvm / ksu_ref |

`Auto_Trigger.yml`、`get-manager.yml`、`main.yml`、`kernel-a12…a16`、`kernel-custom.yml`
同步改为向 `build.yml` 传递新增输入。

## 4. 反检测

| 项 | 做法 |
|---|---|
| `/proc/config.gz` | `scripts/sanitize_ikconfig.py` 原地把 `Image` 内嵌 `.config` 替换为原厂内容（等长重写）：config.gz 仍存在、可读，但不含 `CONFIG_KSU*`、`CONFIG_KSU_SUSFS_*`、`CONFIG_BBG`、`baseband_guard`、伪造的 `LOCALVERSION` |
| SUSFS 日志 | `CONFIG_KSU_SUSFS_ENABLE_LOG` 可关；关闭时补 `SUSFS_LOGI_RL`/`SUSFS_LOGE_RL` 空实现（上游只在开日志时定义，直接关会编译失败） |
| 自检 | 打包前只校验「运行期可达」的特征；`rodata` 命中仅报告，不让构建失败 |

## 5. boot.img / AVB

- KeyMint 版本绑定：boot 分区 AVB 属性 `com.android.build.boot.os_version` /
  `com.android.build.boot.security_patch` 必须与系统侧一致，否则 TEE 生成的证书
  `bootPatchLevel` 会和 `ro.boot.security_patch` 对不上（检测项 `Tampered Attestation Key(26)`）；
- 打包尺寸：`--partition_size` 不再写死 64 MB，改为仓库变量 `BOOT_PARTITION_SIZE`
  （测试机 `boot_a` 为 `100663296`），并在构建后断言产物大小与之相等，避免 AVB footer 不在分区末尾。

## 6. SUSFS 兼容命令（`0x55560` / `0x55580`）

susfs4ksu v2.2.0 重构 sus_mount 后，内核删除了这两条命令的分发，但用户态 `ksu_susfs`
仍保留子命令，调用会返回 `CMD 0x55560 not supported`。本仓库补回实现：

- `patches/susfs-legacy/susfs_compat.c`：`susfs_add_sus_mount()`（inode 标记 → 从非 ksu 进程
  的 mounts/mountinfo/mountstats 隐藏）、`susfs_add_try_umount()`（链表 + 在
  `ksu_handle_umount()` 时 `path_umount()`）、`susfs_is_sus_mount()`、
  `susfs_hide_sus_mnts_for_current()`（视口规则：root 与 ksu domain 看全部，
  其余含 isolated/sandboxed uid 90000–99999 一律过滤）
- `scripts/apply_susfs_legacy_cmds.sh`：构建期注入（幂等、能力检测、锚点校验）
- `build.yml`：调用注入脚本 + `.config` 断言 + `Image` 符号校验

细节与验收方法见 `release-notes.md`。

## 7. 工具脚本

| 脚本 | 作用 |
|---|---|
| `sanitize_ikconfig.py` | 原地消毒 `Image` 内嵌 config |
| `apply_susfs_legacy_cmds.sh` | 注入 SUSFS 兼容命令 |
| `validate_workflows.py` | 静态校验 workflow |
| `check_bash_syntax.py` | 抽取 workflow 中的 bash 做语法检查 |
| `verify_susfs_patch.py` | 校验 SUSFS 补丁与 KernelSU 版本是否匹配 |
| `make_migration_patch.py` | 生成迁移补丁 |

## 8. 文档

| 文件 | 内容 |
|---|---|
| `official-kernelsu-migration.md` / `.patch` | 从 SukiSU 迁移到官方 KernelSU 的改动与验证 |
| `detection-hardening.md` | 反检测分析、`/proc/config.gz`、`Tampered Attestation Key(26)`、SUSFS 命令 |
| `change-inventory.md` | 本文 |
| `release-notes.md` | 发布说明（产物、刷入、验收、回滚） |

## 9. 配置与仓库变量

- `config/config`：删除 `sukisu` 段，补充 `gki-android13-5.10`；说明 KernelSU 固定官方 main、不支持固定提交；
- **仓库变量（不在 git 中）**：`BOOT_PARTITION_SIZE`，测试机为 `100663296`；未设置时默认 `67108864`。

## 10. 已移除 / 不再使用

| 项 | 说明 |
|---|---|
| SukiSU / KPM / SukiSU 专属挂载 | 迁移到官方 KernelSU 时移除 |
| `CONFIG_IKCONFIG=n` 方案 | 改为原地消毒，`/proc/config.gz` 保持存在 |
| `modules/ts_autorun/`（TrickyStore 日期同步模块） | 曾加入后又移除，当前树中不存在 |

## 11. 发布时需要一并说明的运行条件

1. 仓库变量 `BOOT_PARTITION_SIZE` 必须按目标机型设置，否则 boot.img 尺寸断言会失败；
2. 隐身版需要 `sanitize_config=true`，`/proc/config.gz` 才显示原厂内容；
3. SUSFS 兼容命令需要 `CONFIG_KSU_SUSFS_SUS_MOUNT=y`（默认开启）以及
   `hide_sus_mnts_for_non_su_procs` 处于开启状态。
