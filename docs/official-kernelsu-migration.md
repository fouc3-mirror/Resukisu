# 从 SukiSU 迁移到官方 KernelSU —— 改动与验证报告

## 目标

| 需求 | 落地方式 |
|---|---|
| 编译集成从 SUKISU 改为 **最新官方 KernelSU** | `tiann/KernelSU` `main` 分支 HEAD，通过官方 `kernel/setup.sh` 集成 |
| 官方 **AK3** 内核打包 | `osm0sis/AnyKernel3` `master`，按官方规范排除 `README.md` / `*placeholder*` / `.git` |
| 源码要最新 | `KSU_REF="main"`，每次构建 `git pull` 取最新提交（不取 tag） |
| **不集成 KPM** | 无 `use_kpm` 输入、无 KPM patch 步骤；defconfig 强制 `# CONFIG_KPM is not set` |
| **集成 SUSFS** | 所有入口工作流 `enable_susfs: true`；分支按 `gki-{android}-{kernel}` 自动匹配 |
| **内核名称保持官方** | 删除自定义 release name / `version` 后缀注入，沿用上游 GKI 命名 |
| 保留其余自定义构建 | ZRAM/LZ4KD/LZ4K_OPLUS、BBG、一加 8E、Android 12 ramdisk boot、gzip/lz4 boot、`.rej` 收集、ccache、glibc 修复等全部保留 |

## 改动清单

| 文件 | 说明 |
|---|---|
| `.github/workflows/build.yml` | 官方 KSU setup、官方 AK3、SUSFS 分支/补丁名自动推导、移除变体分支、KPM 剔除、内核名保持官方、产物名改为 `KernelSU_*` |
| `.github/workflows/main.yml` | 输入项 13 → 10（GitHub 上限 10）；发布说明固定 `KernelSU (main)`；修复 `SUS_VER` / `BBG_STATUS` / `LZ4_STATUS` / `LZ4_SUFFIX` 未定义 |
| `.github/workflows/get-manager.yml` | 只拉官方 `tiann/KernelSU` 的 `build-manager.yml` 产物，版本号 `20000 + commit 数` |
| `.github/workflows/kernel-a12-5-10.yml` 等 5 个 | 修复非法 `type: string` + `options`；补上未声明的 `called_from_main` / `supp_op`；移除变体选项；`enable_susfs: true` |
| `.github/workflows/kernel-custom.yml` | 修复上游非法键 `输入:` / `默认:`；输入 12 → 9 |
| `.github/workflows/Auto_Trigger.yml` | 修复 `on:` 被写成 `于:`（原文件无触发器）；改为跟踪 `tiann/KernelSU` main |
| `.github/workflows/build-ak3.yml` | **新增**：单版本一键出包入口，预检 ACK 分支 → 编译 → 只上传 AK3 zip |
| `config/config` | 移除 `sukisu=`；新增 `gki-android13-5.10` / `gki-android16-6.12`；SUSFS 自定义 commit 保留 |
| `README.md` / `README-EN.md` | 文档同步为官方 KernelSU |
| `scripts/validate_workflows.py` | 静态校验脚本（见下） |
| `scripts/verify_susfs_patch.py` | SUSFS 补丁对 KernelSU main 的 dry-run 校验 |
| `scripts/make_migration_patch.py` | 与 upstream `dev` 生成统一 diff |
| `docs/official-kernelsu-migration.patch` | 相对 upstream `dev` 的完整改动补丁 |

## 验证结果

### 1. actionlint（12 个 workflow）

```
actionlint -no-color -shellcheck= -pyflakes= .github/workflows/*.yml
exit=0
```

### 2. 静态校验 `scripts/validate_workflows.py`

```
== 1/6 YAML structure ==            12 个文件均合法、均有触发器
== 2/6 legacy variants removed ==   无 SukiSU / ReSukiSU / Next / MKSU 集成残留
== 3/6 KPM not integrated ==        无 use_kpm、无 KPM patch、CONFIG_KPM 强制关闭
== 4/6 official KernelSU setup ==   setup.sh + bash -s -- "$KSU_REF"，KSU_REF=main
== 5/6 official AnyKernel3 ==       osm0sis/AnyKernel3 @ master，官方排除规则
== 6/6 SUSFS forced on ==           6 个入口工作流均 enable_susfs: true
ALL CHECKS PASSED
```

### 3. SUSFS × 官方 KernelSU main 兼容性 dry-run

对每个 SUSFS 分支的 `kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch`，
逐 hunk 校验其上下文/删除行是否仍存在于 `tiann/KernelSU@main` 当前文件：

| SUSFS 分支 | 文件 | hunk | 失败 | 缺失文件 | 最大偏移 |
|---|---|---|---|---|---|
| gki-android12-5.10 | 32 | 112 | 0 | 0 | 0 |
| gki-android13-5.10 | 32 | 112 | 0 | 0 | 0 |
| gki-android13-5.15 | 32 | 112 | 0 | 0 | 0 |
| gki-android14-6.1 | 32 | 112 | 0 | 0 | 0 |
| gki-android15-6.6 | 32 | 112 | 0 | 0 | 0 |
| gki-android16-6.12 | 32 | 112 | 0 | 0 | 0 |

结论：**全部 6 个 SUSFS 分支的 KernelSU 侧补丁都能对最新 KernelSU main 零偏移干净应用。**

### 4. 关键修正：删除会破坏补丁的 `sed`

旧流程里有：

```sh
sed -i 's|kernel/Makefile|kernel/Kbuild|g' ./10_enable_susfs_for_ksu.patch
```

但该补丁同时真实修改 `kernel/Kbuild`、`kernel/Kconfig` 和 `kernel/Makefile`
（dry-run 已确认），这条 `sed` 会把 `kernel/Makefile` 的路径改坏，导致补丁应用失败。
现已删除，改为 `patch -p1 --dry-run --forward` 预检 + `-F 3` 容错回退。

### 5. Bash 语法检查（与上游做对照）

`scripts/check_bash_syntax.py` 会抽出全部 63 个 `run:` 脚本，替换掉 `${{ ... }}`
后交给 bash 解析器检查：

| 代码树 | 脚本数 | 解析失败 |
|---|---|---|
| 迁移后 | 63 | 11 |
| 上游 `dev` 原样 | 65 | 11 |

失败项与上游**完全相同**（同一批步骤，仅序号偏移），全部是旧版解析器不支持的
bash 语法：`<<<`、`<(...)`、`declare -A`、`$'\t'`、双引号内 `\"`。
即：迁移**没有引入任何新的 bash 语法问题**。

顺带做了两处健壮化：

- `SUSFS_PATCH_FILE="${A:-x${B}y}"` 嵌套展开改为显式 `if [ -z ... ]`，可读性更好
- `get-manager.yml` 的 `jq` 由拼接引号改为 `jq -r --arg name / --argjson n`，消除转义隐患

## 构建入口

| 入口 | 说明 |
|---|---|
| `main.yml` | 主入口，勾选版本批量构建 + 可选发布 |
| **`build-ak3.yml`** | **单版本一键出 AK3 包**：预检 ACK 分支 → 编译 → 只上传 `*AnyKernel3.zip` |
| `kernel-a12-5-10.yml` … `kernel-a16-6-12.yml` | 各版本固定矩阵构建 |
| `kernel-custom.yml` | 自定义 Android/内核版本、子版本、补丁级别组合 |

所有入口固定：官方 KernelSU + 强制 SUSFS + 无 KPM。

### 用 `build-ak3.yml` 出包

按手机「设置 → 关于手机 → 内核版本」填写即可，例如
`6.6.118-android15-8-g0908354dac1b` → `android15` / `6.6` / `118`。

```bash
gh workflow run build-ak3.yml \
  -f android_version=android15 \
  -f kernel_version=6.6 \
  -f sub_level=118 \
  -f os_patch_level=2026-01 \
  -f use_bbg=true
```

产物：`AK3-android15-6.6.118-2026-01`，内含
`android15-6.6.118-2026-01-AnyKernel3.zip`。

> `os_patch_level` 需与 ACK 分支名对应（`common-android15-6.6-2026-01`）。
> 预检任务会先 `git ls-remote` 校验该分支，不存在则直接失败，不会白跑 30 分钟编译。

## 注意

- `config/config` 中 `custom=true` 仍可固定 SUSFS 提交；KernelSU 固定跟随官方 `main`，不支持固定。
- `main.yml` 的 Release 任务仍带 `github.repository == 'zzh20188/GKI_KernelSU_SUSFS'` 限制（fork 不发布，只出 artifact），这是原有行为，未改动。
- `ShirkNeko/SukiSU_patch` 仅作为 **ZRAM/LZ4KD 补丁来源**保留，与 KernelSU 集成无关；如不需要 LZ4KD 可关闭 `use_zram`。
