# 反检测分析：为什么“原厂内核不暴露，自编译内核暴露”

被检测的不是 `uname`，而是**内核里内嵌的那份 `.config`**。

## 1. 证据怎么来的

原厂 `boot.img` 和我们编的 `boot.img` 都是 header v4、`ramdisk_size=0`，
内核镜像里都带 `IKCFG_ST` … `IKCFG_ED` 包裹的 gzip 段 —— 这就是运行时
`/proc/config.gz` 的内容（`CONFIG_IKCONFIG=y` + `CONFIG_IKCONFIG_PROC=y`）。
把两边的 gzip 段解出来做逐行 diff，只有 47 行不同：

| 配置 | 原厂 | 我们（修复前） |
|---|---|---|
| `CONFIG_LOCALVERSION` | `"-4k"` | `"-g0908354dac1b-ab16143355-4k"` |
| `CONFIG_KSU` | 无 | `=y` |
| `CONFIG_KSU_SUSFS*` | 无 | `=y` ×11（SUS_PATH / SUS_MOUNT / SUS_KSTAT / SPOOF_UNAME / ENABLE_LOG / HIDE_KSU_SUSFS_SYMBOLS / SPOOF_CMDLINE_OR_BOOTCONFIG / OPEN_REDIRECT / SUS_MAP …） |
| `CONFIG_LSM` | `…,selinux,smack,…` | `…,selinux,baseband_guard,smack,…` |
| `CONFIG_BBG` | 无 | `=y` |
| `CONFIG_LTO_*` | `CONFIG_LTO_NONE=y` | `CONFIG_LTO_CLANG_THIN=y` |
| `CONFIG_TMPFS_XATTR/POSIX_ACL` | 未设 | `=y` |

其余 7700+ 行完全一致（`CONFIG_CC_VERSION_TEXT`、`MODULE_SIG*`、
`DEBUG_INFO_BTF`、`HARDENED_USERCOPY`、`CFI_CLANG` 等都和原厂一样）。

也就是说：**原厂内核的 config.gz 里没有 KSU/SUSFS/BBG 的“补丁痕迹”，我们的有。**
只要检测软件读一次 `/proc/config.gz`，`CONFIG_KSU=y` 就是铁证。

内核镜像里还能直接搜到这些字符串（修复前实测）：

```
IKCFG_ST        ×1
CONFIG_KSU      ×10
baseband_guard  ×9
vc-teahouse     ×1
```

## 2. 修复内容

`build.yml` 新增三个开关（默认关闭，保持原有行为）：

- `hide_kernel_config`：把 `CONFIG_IKCONFIG` 设为 n。
  `.config` 不再被打进镜像 → `/proc/config.gz` 不存在，
  `CONFIG_KSU*` / `CONFIG_BBG` / 伪造的 `CONFIG_LOCALVERSION` 全部不可见。
  镜像里连 `IKCFG_ST` 都没有，CI 会强制校验。
- `disable_susfs_log`：`CONFIG_KSU_SUSFS_ENABLE_LOG=n`，内核日志不再出现 `susfs:`。
- `lto`：`auto | none | thin`。原厂是 `CONFIG_LTO_NONE=y`，`none` 可对齐原厂。

`build-ak3-stealth.yml` 把这四项全打开，另外 `use_bbg: false`：

- BBG 会在 `CONFIG_LSM` 里注册 `baseband_guard`，`/sys/kernel/security/lsm`
  会多出一项，镜像里还留着 `https://github.com/vc-teahouse/Baseband-guard`。
  自编译内核 + 多出来的 LSM，本身就是“内核被改”的强特征。

## 3. 其余保持原厂特征

- `uname -r` = `6.6.118-android15-8-g0908354dac1b-ab16143355-4k`
- `uname -v` = `#1 SMP PREEMPT Thu Aug 20 09:40:32 UTC 2026`
- `vermagic` 与上面一致，原厂 vendor 模块仍可加载
- `CONFIG_CC_VERSION_TEXT` 与原厂逐字相同（同一套 clang 18.0.0 / LLD 18.0.0）

## 4. 验证结果（隐身版 vs 上一版）

对 `build-ak3-stealth.yml` 产出的 `boot.img` 直接做字节级比对：

| 特征 | 上一版 | 隐身版 | 说明 |
|---|---|---|---|
| `IKCFG_ST` / `IKCFG_ED` | 1 / 1 | **0 / 0** | `/proc/config.gz` 完全没有，`.config` 不再进镜像 |
| `baseband_guard` | 9 | **0** | LSM 列表与原厂一致 |
| `vc-teahouse` | 1 | **0** | BBG 代码未再进入镜像 |
| `susfs:[` （日志格式串） | 有 | **0** | `CONFIG_KSU_SUSFS_ENABLE_LOG=n` 生效 |
| `KernelSU` 字符串 | 329 | 仍有 | 必然存在，属 rodata |
| `CONFIG_KSU` | 10 | 9 | 只剩 9 条 `CONFIG_KSU_SUSFS_*` 特性名，来自 `susfs_get_enabled_features()`，只有 root 通过 ioctl 才读得到 |
| `uname -r` | 正确 | 正确 | `6.6.118-android15-8-g0908354dac1b-ab16143355-4k` |
| `uname -v` | 正确 | 正确 | `#1 SMP PREEMPT Thu Aug 20 09:40:32 UTC 2026` |
| `Image` 大小 | 38,046,208 | 37,001,728 | 原厂 36,801,024，`LTO=none` 后更接近 |

## 5. 仍存在的风险（改不掉或代价太大）

1. `/sys/kernel/btf/vmlinux`（`CONFIG_DEBUG_INFO_BTF=y`，原厂也有）
   是 BTF 类型表，里面能看到内核符号名。关掉会让 vendor 的 BPF/CO-RE 程序失效，
   不能动。SUSFS 的 `HIDE_KSU_SUSFS_SYMBOLS` 只处理 kallsyms，不处理 BTF。
2. 模块签名证书：每次 CI 都现场 `openssl` 生成一对密钥（`CONFIG_MODULE_SIG_ALL=y`
   会把证书编进内核），x509 有效期就是 CI 的真实构建时间（如 `261107155219Z`），
   和伪造的 `uname -v` 对不上。只有 root 通过 `/proc/keys` 或直接读镜像才看得到，
   普通 App 没有这个入口。
3. `/proc/kallsyms`：需要 root 才能读，SUSFS 已做符号隐藏。
4. `boot.img` 未做 AVB 签名。刷入后 Verified Boot 状态必然从 green 变 orange，
   这类“系统完整性”检测和内核本身无关，属于解锁 bootloader 的固有代价。
