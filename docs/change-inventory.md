# 变更清单（相对上游 `haidayne/Resukisu@36309b1`）

> 用于发布说明/审阅：本仓库相对上游 fork 点的**全部**改动，不只有 SUSFS 兼容命令。

## 0. 统计

```
27 files changed, 5511 insertions(+), 974 deletions(-)
```

对比基准：`haidayne/Resukisu` 的 `dev` 分支 `36309b1`（2026-03-10）；
本仓库基线：`af4f41c`（把上游 tree 整体导入后的第一个提交）。

---

## 1. 一句话总结

把构建链从 **SUKISU** 换成 **官方 KernelSU + 官方 AnyKernel3**，SUSFS 固定 v2.3.0 系列补丁，
再叠加一层**反检测加固**（config.gz 消毒、日志/符号处理、LTO 与 LOCALVERSION 对齐原厂），
最后补回 SUSFS v2.x 被删掉的 **`add_sus_mount` / `add_try_umount`** 两条命令。

---

## 2. 按主题

### A. 构建主链 —— `.github/workflows/build.yml`（+861 / −?）

| 区块 | 改动 |
|---|---|
| KernelSU | 改用官方 `tiann/KernelSU`（`setup.sh` + `KSU_REF`），移除 SukiSU 分支逻辑、KPM、SukiSU 专属挂载 |
| AnyKernel3 | 优先 `WildKernels/AnyKernel3@gki-2.0`；检测到上游示例 `anykernel.sh`（`device.name1=maguro`）时替换为 GKI 安全模板（`BLOCK=auto` / `IS_SLOT_DEVICE=auto` / `split_boot`），并加 GKI 内核版本闸门 |
| SUSFS | 分支由 `gki-<android>-<kernel>` 决定；主补丁 + `KernelSU/10_enable_susfs_for_ksu.patch`；WildKernels 兼容补丁**缺失时跳过**而不是失败 |
| 内核配置 | `CONFIG_KSU_SUSFS*` 10 项写入 defconfig；`CONFIG_BBG` 可选；ZRAM LZ4KD 可选；`check_defconfig` 关闭 |
| 隐身 | `CONFIG_LOCALVERSION` 可控并回读校验；LTO 与原厂对齐（`--lto=none` 可关）；`CONFIG_KSU_SUSFS_ENABLE_LOG` 可关（并补 `SUSFS_LOGI_RL` 空实现）；`/proc/config.gz` 内容替换为原厂内容 |
| 时间戳 | `KBUILD_BUILD_TIMESTAMP` + 改写 `scripts/mkcompile_h` 的 `UTS_VERSION` → `#1 SMP PREEMPT <指定时间>` |
| boot.img | header v4；`--os_version` / `--os_patch_level`；**AVB 属性** `com.android.build.boot.os_version` / `…security_patch`；`--partition_size` 取仓库变量 `BOOT_PARTITION_SIZE`；构建后**尺寸断言**（必须等于分区大小） |
| SUSFS 兼容命令 | 注入 `fs/susfs_compat.c` + 4 处 hook；`.config` 断言；`Image` 符号校验 |

### B. 打包入口 —— 3 个 workflow

| 文件 | 用途 | 关键输入 |
|---|---|---|
| `build-ak3.yml`（新增，169 行） | 单版本 AK3 打包（标准版） | android/kernel/sub_level/os_patch_level/revision/build_time/kernel_localversion/use_zram/use_bbg |
| `build-ak3-stealth.yml`（新增，271 行） | **隐身版** AK3：`sanitize_config=true`，可关 BBG、关日志、选 LTO | 上述 + `boot_security_patch` |
| `build-ak3-toggle.yml`（新增，166 行） | 开关版：以 4 个布尔量（cfg/bbg/log/lto）组合做二分排查 | hide_kernel_config / use_bbg / disable_susfs_log / lto |

配套改动：`Auto_Trigger.yml`、`get-manager.yml`、`main.yml`、`kernel-a12…a16`、`kernel-custom.yml`
都改为向 `build.yml` 传递新增输入（否则新参数不会生效）。

### C. 反检测（`docs/detection-hardening.md` 记录全过程）

- `scripts/sanitize_ikconfig.py`（新增 176 行）：**原地**把 `Image` 里内嵌的 `.config`
  替换成原厂内容（等长重写），保留 `CONFIG_IKCONFIG`/`/proc/config.gz` 的存在与可读性，
  但里面不再有 `CONFIG_KSU*`、`CONFIG_KSU_SUSFS_*`、`CONFIG_BBG`、`baseband_guard`、伪造的 `LOCALVERSION`；
- 关闭 SUSFS 日志时补 `SUSFS_LOGI_RL`/`SUSFS_LOGE_RL` 空实现（上游只在开日志时定义，直接关会编译失败）；
- 包内自检步骤：只检查**运行期可达**的特征，`rodata` 命中只做报告不失败。

### D. SUSFS 兼容命令（本次，详见 `release-susfs-legacy.md`）

- `patches/susfs-legacy/susfs_compat.c`（新增 310 行）
- `scripts/apply_susfs_legacy_cmds.sh`（新增 147 行）
- `build.yml` 新增：注入调用、`.config` 断言、`Image` 符号校验

### E. 工具脚本（`scripts/`，新增 6 个）

| 脚本 | 作用 |
|---|---|
| `sanitize_ikconfig.py` | 原地消毒 `Image` 内嵌 config |
| `apply_susfs_legacy_cmds.sh` | 注入 SUSFS 兼容命令（幂等、能力检测） |
| `validate_workflows.py` | 静态校验 workflow（步骤/输入/权限） |
| `check_bash_syntax.py` | 抽取 workflow 里的 bash 做语法检查 |
| `verify_susfs_patch.py` | 校验 SUSFS 补丁与 KernelSU 版本是否匹配 |
| `make_migration_patch.py` | 生成 `official-kernelsu-migration.patch` |

### F. 文档

| 文件 | 内容 |
|---|---|
| `docs/official-kernelsu-migration.md`（新增） | 从 SukiSU 迁移到官方 KernelSU 的改动与验证报告 |
| `docs/official-kernelsu-migration.patch`（新增，2337 行） | 迁移补丁本体 |
| `docs/detection-hardening.md`（新增 257 行） | 反检测分析；§6 记录 KeyMint/26；§7 记录本次 SUSFS 命令 |
| `docs/release-susfs-legacy.md`（新增 290 行） | 发布说明（产物/工作流/代码/验收/回滚） |

### G. 配置与仓库变量

- `config/config`：去掉 `sukisu` 段，补 `gki-android13-5.10`，说明 KernelSU 固定官方 main、不提供固定提交；
- **仓库变量（不在 git 里）**：`BOOT_PARTITION_SIZE = 100663296`（本机 `boot_a` 真实大小，96 MB）。
  未设置时默认 `67108864`（64 MB）。

### H. README

`README.md` / `README-EN.md`：改为官方 KernelSU 的描述，补本仓库文档入口。

---

## 3. 逐提交（24 条）

| # | commit | 标题 | 主要文件 |
|---|---|---|---|
| 1 | `af4f41c` | 迁移基线：官方 KernelSU + SUSFS GKI + 官方 AnyKernel3 | 全量 tree |
| 2 | `722092f` | WildKernels 兼容补丁改为可选 | build.yml |
| 3 | `7772526` | AnyKernel3 用 GKI 配置，替换上游示例 | build.yml, scripts/validate_workflows.py |
| 4 | `237fe17` | build_time 默认取真实构建时间 | build-ak3.yml |
| 5 | `20c70af` | 支持强制 `CONFIG_LOCALVERSION` 并回读校验 | build.yml, build-ak3.yml |
| 6 | `088b282` | 6.6 bazel 长构建不再被杀 | build.yml |
| 7 | `74716a3` | 隐去 config.gz、去掉 BBG、LTO 对齐原厂 | build.yml, build-ak3-stealth.yml |
| 8 | `21ee976` | 记录 config.gz 检测分析 | detection-hardening.md |
| 9 | `fc97494` | 关日志时补 `SUSFS_LOGI_RL` 空实现 | build.yml |
| 10 | `94bc8cd` | 自检只拦运行期可达特征，rodata 只报告 | build.yml, detection-hardening.md |
| 11 | `8f7a26f` | 记录模块签名证书日期是残余特征 | detection-hardening.md |
| 12 | `6a48702` | 新增开关版 workflow（二分排查） | build-ak3-toggle.yml |
| 13 | `a27e598` | 原地消毒 config.gz（不再删 IKCONFIG） | build.yml, build-ak3-stealth.yml, scripts/sanitize_ikconfig.py |
| 14 | `b9de926` | 仅当 BBG 关闭时才要求签名缺失 | build-ak3-stealth.yml |
| 15 | `4231aab` | 写回 KeyMint 版本绑定的 boot AVB 属性 | build.yml, build-ak3-stealth.yml |
| 16 | `305d32b` | 记录 26 的根因（boot AVB 属性） | detection-hardening.md |
| 17 | `d5d4924` | ts_autorun 默认 mode 1（**已撤销**） | modules/ts_autorun/* |
| 18 | `7c5873b` | boot.img 按真实分区大小打包 | build.yml, modules/ts_autorun/run.sh |
| 19 | `c80ff86` | 撤销 ts_autorun（26 按小米已知误报处理） | modules/ts_autorun/* |
| 20 | `5a6f78b` | 记录 26 不修的结论 | detection-hardening.md |
| 21 | `494f2b7` | 补回 0x55560 / 0x55580 | patches/, scripts/, build.yml, docs |
| 22 | `aedaec8` | add_try_umount 真卸载 + add_sus_mount 真隐藏 | 同上 |
| 23 | `ae9d27b` | 修编译（extern + slab.h） | susfs_compat.c |
| 24 | `8ad2c15` | 发布说明 | README.md, docs/release-susfs-legacy.md |

---

## 4. 已撤销 / 不在当前树里的内容

| 项 | 状态 |
|---|---|
| `modules/ts_autorun/`（TrickyStore 补丁日期同步模块，v1.2） | 加过（`d5d4924`、`7c5873b`）→ 已撤销（`c80ff86`），当前树中不存在 |
| SukiSU / KPM / SukiSU 专属挂载逻辑 | 迁移时移除 |
| `CONFIG_IKCONFIG=n` 方案 | 改为原地消毒（`a27e598`），config.gz 仍存在 |

---

## 5. 发布时需要一起说明的运行期条件

1. 仓库变量 `BOOT_PARTITION_SIZE` 必须按目标机型设置（本机 `100663296`），否则 boot.img 尺寸断言会失败；
2. 隐身版依赖 `sanitize_config=true`，`/proc/config.gz` 才会显示原厂内容；
3. SUSFS 兼容命令依赖 `CONFIG_KSU_SUSFS_SUS_MOUNT=y`（默认已开）与用户的 `hide_sus_mnts_for_non_su_procs 1`。
