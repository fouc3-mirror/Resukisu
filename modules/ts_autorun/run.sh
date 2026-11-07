#!/system/bin/sh
#
# 读取系统真实补丁日期，写入 TrickyStore 的 security_patch.txt
#
# 默认使用模式1（vendor 也写真实补丁日期），不再询问。
# 需要使用模式2（vendor=prop）时，带参数运行：sh "本脚本.sh" 2
#
# 可用环境变量覆盖路径（方便测试）：
#   TS_DIR     默认 /data/adb/tricky_store
#   BUILDPROP  默认 /system/build.prop

set -u

TS_DIR="${TS_DIR:-/data/adb/tricky_store}"
BUILDPROP="${BUILDPROP:-/system/build.prop}"
OUT="$TS_DIR/security_patch.txt"

[ -t 1 ] && clear

if [ ! -d "$TS_DIR" ]; then
    echo "$TS_DIR 目录不存在,请先安装Tricky Store/TEESimulator/TEESimulator-RS模块"
    echo "($TS_DIR directory does not exist, please install Tricky Store/TEESimulator/TEESimulator-RS module first)"
    exit 1
fi

# ---- 选择模式：默认 2，可用第一个参数覆盖 ----
user_choice="${1:-1}"
case "$user_choice" in
    1|2) ;;
    *)
        echo "无效参数 '$user_choice'，默认使用模式1 (Invalid argument. Defaulting to Mode 1)"
        user_choice=1
        ;;
esac
echo "已选择模式$user_choice (Mode $user_choice)"

# ---- 取真实补丁日期：先 getprop，再退回 build.prop ----
patch_date_full="$(getprop ro.build.version.security_patch 2>/dev/null || true)"

if [ -z "$patch_date_full" ] && [ -r "$BUILDPROP" ]; then
    patch_line="$(grep "^ro.build.version.security_patch=" "$BUILDPROP" 2>/dev/null || true)"
    [ -n "$patch_line" ] && patch_date_full="${patch_line#*=}"
fi

# ---- 校验格式 YYYY-MM-DD，避免写出垃圾值 ----
case "$patch_date_full" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*) ;;
    *)
        echo "未取到有效的补丁日期 (got: '${patch_date_full:-empty}')，已中止，未修改任何文件"
        echo "Failed to read a valid security patch date, aborting without changes."
        exit 1
        ;;
esac

patch_date_yyyymm="$(echo "$patch_date_full" | cut -d'-' -f1-2 | tr -d '-')"
echo "补丁日期 (patch date): $patch_date_full  ->  system=$patch_date_yyyymm"

# ---- 备份：只在没有有效备份时创建，不覆盖已有备份 ----
if [ -f "$OUT" ]; then
    if [ ! -s "$OUT.bak" ]; then
        cp -f "$OUT" "$OUT.bak" && echo "已备份为 security_patch.txt.bak (backed up)"
    else
        echo "已有有效备份 security_patch.txt.bak，保留不动 (existing backup kept)"
    fi
fi

# ---- 生成内容：先写临时文件再替换，避免写一半 ----
tmp="$OUT.tmp.$$"
{
    echo "system=$patch_date_yyyymm"
    echo "boot=$patch_date_full"
    case "$user_choice" in
        1) echo "vendor=$patch_date_full" ;;
        2) echo "vendor=prop" ;;
    esac
} > "$tmp" || { echo "写入失败 (write failed)"; rm -f "$tmp"; exit 1; }

mv -f "$tmp" "$OUT" || { echo "替换失败 (replace failed)"; rm -f "$tmp"; exit 1; }

echo "已生成 $OUT ($OUT generated successfully)"
cat "$OUT"
