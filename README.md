<div align="center">

# GKI KernelSU SUSFS
### 🏮 2026 🐎 Happy New Year! 🏮

**自动化构建 GKI 内核 | 集成 KernelSU + SUSFS**

[![Release](https://img.shields.io/github/v/release/zzh20188/GKI_KernelSU_SUSFS?label=Release&style=flat-square&logo=github&logoColor=white&color=2ea44f)](https://github.com/zzh20188/GKI_KernelSU_SUSFS/releases)
[![Coolapk](https://img.shields.io/badge/Follow-Coolapk-3DDC84?style=flat-square&logo=android&logoColor=white)](http://www.coolapk.com/u/11253396)
[![KernelSU](https://img.shields.io/badge/KernelSU-Supported-5AA300?style=flat-square)](https://kernelsu.org/)
[![SUSFS](https://img.shields.io/badge/SUSFS-Integrated-E67E22?style=flat-square)](https://gitlab.com/simonpunk/susfs4ksu)

[**English**](README-EN.md) | 简体中文

---

</div>

## 🚀 快速导航

<table>
<tr>
<td align="center" width="33%">📖 <b><a href="https://github.com/zzh20188/GKI_KernelSU_SUSFS/wiki">文档</a></b></td>
<td align="center" width="34%">📥 <b><a href="https://github.com/zzh20188/GKI_KernelSU_SUSFS/releases">下载</a></b></td>
<td align="center" width="33%">🔰 <b><a href="https://github.com/zzh20188/GKI_KernelSU_SUSFS/wiki/Fork%E4%B8%8E%E8%87%AA%E5%AE%9A%E4%B9%89%E7%BC%96%E8%AF%91%E6%8C%87%E5%8D%97">新手自定义构建必看</a></b></td>
</tr>
</table>

---

## ⚠️ 兼容性提醒

> **注意：** 目前不支持一加 ColorOS 14、15，刷入后可能需要清除数据开机。

> **KernelSU：集成官方 [tiann/KernelSU](https://github.com/tiann/KernelSU) `main` 分支最新源码，内核名称保持官方原样，不注入自定义后缀**
>
> **不集成 KPM：defconfig 与刷入镜像均不含 KPM 功能**

> **Android 16：已支持 Android 16 - 6.12 内核版本**


---

## 📚 文档与指南

详细说明请查阅 [**GitHub Wiki（中英双语）**](https://github.com/zzh20188/GKI_KernelSU_SUSFS/wiki)

Wiki 涵盖内容：
- [**🔰 新手必看**](https://github.com/zzh20188/GKI_KernelSU_SUSFS/wiki/Fork%E4%B8%8E%E8%87%AA%E5%AE%9A%E4%B9%89%E7%BC%96%E8%AF%91%E6%8C%87%E5%8D%97)
- 📥 下载/刷入内核
- 💡 使用技巧 Tips
- 🆘 救砖指南
- 📊 内核版本兼容性说明

本仓库内的补充文档：
- [SUSFS v2.x 兼容命令（`0x55560` / `0x55580`）发布说明](docs/release-susfs-legacy.md) —— 手动挂载点隐藏/卸载
- [变更清单（相对上游的全部改动）](docs/change-inventory.md)
- [反检测分析：为什么“原厂内核不暴露，自编译内核暴露”](docs/detection-hardening.md)

---

## ❗构建失败常见原因（KernelSU / SUSFS 更新不同步）

内核侧固定集成**官方 KernelSU**，SUSFS 则按 Android / 内核版本匹配对应分支，两者更新节奏不一致时构建可能失败：

- KernelSU main 分支：<https://github.com/tiann/KernelSU/commits/main>
- SUSFS 各版本分支：<https://gitlab.com/simonpunk/susfs4ksu>

例如：SUSFS 刚更新了内核补丁格式，而官方 KernelSU 侧补丁还没跟进适配，这时打补丁/编译就容易失败。

如出现以下情况，请等待上游（KernelSU 或 SUSFS）完成适配，或在下面通过 `config/config` 指定稳定的 SUSFS 提交。

<img src="assets/susfs_eg1.png" alt="SUSFS gki-android14-6.1 更新记录" width="80%">

## 🔧 自定义提交配置
通过 [`config/config`](config/config) 文件可以指定 SUSFS 使用特定的 commit（KernelSU 固定跟随官方 `main` 最新提交，不支持固定）。

**什么是提交 (commit)？**

提交是一串哈希字符串，代表仓库在某个时间点的状态。例如将 `gki-android14-6.1` 设为 `4b8644515fe6d87a109129e590ccd9d33a855dca`，即使用该时间点的 SUSFS 版本编译内核。

**为什么要指定提交？**

- 当上游仓库更新引入 bug 或兼容性问题时，可回退到稳定版本
- 当 KernelSU 与 SUSFS 版本不同步导致编译失败时，可手动指定兼容的版本

**如何获取提交哈希？**

- SUSFS: https://gitlab.com/simonpunk/susfs4ksu/commits/

先选择分支，再复制对应提交的哈希值：

![选择分支](assets/susfs_branch.png)
![复制提交](assets/susfs_commit.png)

```ini
# 启用自定义提交
custom=true

# SUSFS 各分支的 commit hash
gki-android12-5.10=
gki-android13-5.10=
gki-android13-5.15=
gki-android14-6.1=
gki-android15-6.6=
gki-android16-6.12=
```

> 留空则使用该分支的最新提交。

---

## 🧪 伪装 `/proc/config.gz`（Stock Config）

这是一个进阶技巧，不需要在工作流里手动开关。  
构建时会自动检测 `config/stock_defconfig` 是否存在：存在则应用，不存在则跳过。

使用方法：
1. 确保设备当前是官方 ROM + 官方内核。
2. 获取设备上的 `/proc/config.gz`（可在手机端或电脑端操作）。
3. 解压后重命名为 `stock_defconfig`，上传到仓库 [`config/`](config/) 目录并提交（可直接在手机端完成）。

构建流程会自动：
- 复制到内核源码：`$KERNEL_ROOT/common/arch/arm64/configs/stock_defconfig`
- 在 `$KERNEL_ROOT/common/kernel/Makefile` 中将 `$(obj)/config_data` 规则从 `$(KCONFIG_CONFIG)` 切换为 `arch/arm64/configs/stock_defconfig`
- 使编译产物中的 `/proc/config.gz` 更贴近你的官方内核配置
---

## 🛠️ 安装后推荐

### 📦 模块推荐

<table>
<tr>
<th>模块名称</th>
<th>仓库</th>
<th>频道</th>
</tr>
<tr>
<td><b>LSPosed-Irena</b></td>
<td><a href="https://github.com/re-zero001/LSPosed-Irena">GitHub</a></td>
<td><a href="https://t.me/lsposed_irena">Telegram</a></td>
</tr>
<tr>
<td><b>Zygisk Next</b></td>
<td><a href="https://github.com/Dr-TSNG/ZygiskNext">GitHub</a></td>
<td rowspan="2"><a href="https://t.me/real5ec1cff">Telegram</a></td>
</tr>
<tr>
<td><b>TrickyStore</b></td>
<td><a href="https://github.com/5ec1cff/TrickyStore">GitHub</a></td>
</tr>
</table>

### 🔧 Xposed 模块

| 模块 | 说明 |
|:---:|:---|
| **FuseFixer** | [Unicode零宽修复模块](https://t.me/real5ec1cff/268) |

### App

| 名称 | 说明 |
|:---:|:---|
| **Scene** | [官网](https://omarea.com/#/) |
---

<div align="center">

**更多内容持续更新中...**

⭐ 如果这个项目对你有帮助，请点个 Star 支持一下！

</div>
