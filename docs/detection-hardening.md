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
4. `boot.img` 的 AVB 用的是 CI 现生成的测试密钥（`testkey_rsa2048.pem`），
   签名本身有效但不被 bootloader 信任。刷入后 Verified Boot 状态必然从 green 变 orange，
   这类“系统完整性”检测和内核本身无关，属于解锁 bootloader 的固有代价。

## 6. `Tampered Attestation Key(26)`：boot 分区的 KeyMint 版本绑定属性

### 6.1 现象

春秋检测器（Chunqiu Detector）的 `Tampered Attestation Key(26)` 命中，
按该项目的说明，26 号标签的含义是
“**证书 patch 标签与系统属性不一致**”
（[检测项说明](https://github.com/mingzun09/Chunqiu-Detector-Problem-solution/blob/main/language/answer_zh.md)，
官方给的解法是写 `/data/adb/tricky_store/security_patch.txt`）。

### 6.2 另一处差异：重建 boot.img 时把原厂的 AVB 属性丢了

原厂 `boot.img`（同 ROM 的 `images/boot.img`）尾部 vbmeta 的 hash descriptor 里带着
三条 property descriptor：

```
com.android.build.boot.os_version     = 15
com.android.build.boot.fingerprint    = Redmi/warsaw/warsaw:15/AQ3A.250226.002/OS4.0.5.1.XHPCN:user/release-keys
com.android.build.boot.security_patch = 2026-09-01
```

我们自己用 `avbtool add_hash_footer` 重建的 `boot.img` 里，这三条**一条都没有**
（只剩 `sha256` 和 `boot` 两个哈希描述符，`strings` 里也搜不到）。

这层属性的用途写在 AOSP
[Version information in AVB properties](https://source.android.com/devices/bootloader/version-info-avb)：
为了支持 **KeyMint 版本绑定**，bootloader 需要用 `avb_property_lookup()` 从 vbmeta 里
取出每个分区的 OS 版本和补丁级别，再交给 TEE 里的 KeyMint；
KeyMint 把 boot 分区的补丁级别写进密钥证明证书的 `bootPatchLevel` 标签。

所以：属性缺失 → bootloader 没有 boot 分区的 SPL 可交 → 证书里的 boot 补丁标签
为空/0 → 与 `ro.build.version.security_patch`（本机 `2026-10-01`）对不上 → 命中 26。
这也解释了为什么“换回上游产物就正常”：上游产物同样是 `add_hash_footer`，
但它那台设备/那套模块读的是别的来源，而这里 boot 侧完全没数据可读。

顺带说明：原厂 boot 的 `2026-09-01` 与系统侧 `2026-10-01` 本身就差一个月，
所以 Redmi/小米 机型即使不 root 也常报 26（项目文档里也写了“无视即可”）。
我们的做法是**把 boot 侧同步成系统侧的值**，让两边一致。

### 6.3 修复

`build.yml` 的 `构建 Boot 镜像 (Android 13+)` 里给 `mkbootimg` 和 `avbtool` 补上：

```bash
$MKBOOTIMG --header_version 4 --kernel Image --output boot.img \
  --os_version "$BOOT_OS_VERSION_STR" --os_patch_level "$BOOT_PATCH_MONTH"

$AVBTOOL add_hash_footer --partition_name boot --partition_size $((64 * 1024 * 1024)) \
  --image boot.img --algorithm SHA256_RSA2048 --key $BOOT_SIGN_KEY_PATH \
  --prop com.android.build.boot.os_version:15 \
  --prop com.android.build.boot.security_patch:2026-10-01
```

新增输入 `boot_os_version`（留空按 `android_version` 推导）与
`boot_security_patch`（留空按 `<os_patch_level>-01` 推导），
并在构建后加了一步校验：属性缺失直接 fail，不再产出“看起来正常”的包。

本地对已知能开机的镜像做过等长验证：只改 header 的 `os_version`
（0 → `15.0.0` / `2026-10`）并追加两条 prop，`Image` 逐字节不变：

```
header os_version 0x1e0001aa -> 15.0.0 2026-10
props: com.android.build.boot.os_version=15
       com.android.build.boot.security_patch=2026-10-01
kernel identical: True
```

### 6.4 用户态还有一层（用了 TrickyStore/TEESimulator 才需要）

如果设备上装了证书合成类模块（TrickyStore / TEESimulator / OhMyKeymint 等），
证书链是模块自己生成的，patch 标签取自 `/data/adb/tricky_store/security_patch.txt`，
和内核无关。该文件不存在或过期时同样命中 26，需要写成：

```
system=202610
boot=2026-10-01
vendor=2026-10-01
```

（也可直接删掉该文件让模块回落到系统属性；改完必须重启再测。）

### 6.5 本机实测结论：26 的真正来源是 `vendor=prop`

在这台 K90 Ultra 上实测（`adb` + `su` 直接查）：

| 项 | 值 |
|---|---|
| `ro.build.version.security_patch`（system） | `2026-10-01` |
| `ro.vendor.build.security_patch`（vendor） | `2026-09-01` ← 厂商自己就落后一个月 |
| `ro.boot.security_patch` | 空 |
| `/proc/config.gz` | 45,959 B，`CONFIG_KSU` 命中 0 次（消毒版已生效） |
| `security_patch.txt` | `system=202610` / `boot=2026-10-01` / **`vendor=prop`** |

`vendor=prop` 意味着证书里的 `vendorPatchLevel` 直接取 `ro.vendor.build.security_patch`，
也就是 `2026-09-01`，与系统侧 `2026-10-01` 不一致 → 命中 26。
这个值由模块 `ts_autorun`（开机自动跑官方那个 26 号脚本）写入，
其 `config.sh` 里 `MODE=2`（vendor=prop）是默认值，**每次开机都会写回 mode 2**。

修复：`MODE=1`（vendor 也写真实补丁日期），并立刻重跑一次脚本让文件生效，
重启后复测。仓库里 `modules/ts_autorun/` 保存了修正后的模块（v1.2，默认 mode 1），
避免重装旧包时又回到 mode 2。

> 结论：**26 与内核无关**。内核侧能做的只有 6.3 那件事——把 boot 分区的
> KeyMint 版本绑定属性补齐到与原厂一致（去掉证书合成模块后才用得上）。


