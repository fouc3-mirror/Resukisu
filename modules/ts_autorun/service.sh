#!/system/bin/sh
# KernelSU late_start 阶段执行 run.sh，每次开机一次

MODDIR=${0%/*}
case "$MODDIR" in "$0") MODDIR=. ;; esac
[ -f "$MODDIR/config.sh" ] && . "$MODDIR/config.sh"

MODE=${MODE:-1}
DELAY=${DELAY:-0}
BOOTWAIT=${BOOTWAIT:-120}

mkdir -p "$MODDIR/logs" 2>/dev/null

(
    LOG="$MODDIR/logs/service.log"
    if [ -f "$LOG" ] && [ "$(wc -c < "$LOG" 2>/dev/null || echo 0)" -gt 65536 ]; then
        mv -f "$LOG" "$LOG.old"
    fi
    exec >>"$LOG" 2>&1
    echo "===== $(date +'%Y-%m-%d %H:%M:%S') ====="

    boot_id="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)"
    if [ -n "$boot_id" ] && [ -f "$MODDIR/.last_boot" ] &&
       [ "$(cat "$MODDIR/.last_boot" 2>/dev/null)" = "$boot_id" ]; then
        echo "本次开机（$boot_id）已执行过，跳过"
        exit 0
    fi
    echo "boot_id=$boot_id"

    waited=0
    while [ "$waited" -lt "$BOOTWAIT" ]; do
        [ "$(getprop sys.boot_completed 2>/dev/null)" = "1" ] && break
        sleep 2
        waited=$((waited + 2))
    done
    echo "boot_completed 等待 ${waited}s"

    if [ "$DELAY" -gt 0 ] 2>/dev/null; then
        echo "额外延迟 ${DELAY}s"
        sleep "$DELAY"
    fi

    sh "$MODDIR/run.sh" "$MODE"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "run.sh 失败(rc=$rc)，5 秒后重试一次"
        sleep 5
        sh "$MODDIR/run.sh" "$MODE"
        rc=$?
    fi
    echo "run.sh rc=$rc"

    [ -n "$boot_id" ] && echo "$boot_id" > "$MODDIR/.last_boot"
    exit 0
) &

exit 0
