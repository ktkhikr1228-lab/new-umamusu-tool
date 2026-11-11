#!/usr/bin/env bash
# ガイド確認アプリをラズパイで常駐させるための操作スクリプト。
#
#   bash tools/guide_app/guide_app.sh install    # 再起動後も自動で起動するよう登録し、今すぐ起動
#   bash tools/guide_app/guide_app.sh status     # 動いているか確認
#   bash tools/guide_app/guide_app.sh update     # 最新版を取得して再起動(git pull)
#   bash tools/guide_app/guide_app.sh restart    # 再起動
#   bash tools/guide_app/guide_app.sh stop       # 停止(自動起動の登録は残る)
#   bash tools/guide_app/guide_app.sh log        # ログの最後を表示
#   bash tools/guide_app/guide_app.sh uninstall  # 停止して自動起動の登録を外す
#
# 自動起動は既存のアップロード画面と同じく cron の @reboot を使う。
# アプリが落ちても5秒後に自動で立ち上げ直す。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$APP_DIR/../.." && pwd)"
RUN_DIR="$APP_DIR/run"
PID_FILE="$RUN_DIR/guide_app.pid"
LOG_FILE="$RUN_DIR/guide_app.log"
PYTHON="${PYTHON:-$(command -v python3)}"
SELF="$APP_DIR/guide_app.sh"
CRON_MARK="# guide_app autostart"
LOG_LIMIT_BYTES=$((5 * 1024 * 1024))

mkdir -p "$RUN_DIR"

is_running() {
    [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

port() {
    "$PYTHON" -c "import sys; sys.path.insert(0, '$APP_DIR/..'); from guide_app.config import load_config; print(load_config().port)" 2>/dev/null || echo 8090
}

# 落ちても立ち上げ直すループ(内部用)
supervise() {
    cd "$REPO_DIR"
    while true; do
        echo "[$(date '+%F %T')] 起動します"
        "$PYTHON" tools/guide_app serve || true
        echo "[$(date '+%F %T')] 停止しました。5秒後に再起動します"
        sleep 5
    done
}

start() {
    if is_running; then
        echo "すでに動いています(PID $(cat "$PID_FILE"))。http://$(hostname):$(port)/"
        return 0
    fi
    # ログが大きくなりすぎたら1世代だけ残す
    if [[ -f "$LOG_FILE" ]] && (( $(stat -c %s "$LOG_FILE") > LOG_LIMIT_BYTES )); then
        mv -f "$LOG_FILE" "$LOG_FILE.1"
    fi
    setsid bash "$SELF" _supervise >>"$LOG_FILE" 2>&1 < /dev/null &
    echo $! >"$PID_FILE"
    sleep 2
    if is_running; then
        echo "起動しました。http://$(hostname):$(port)/  (ログ: $LOG_FILE)"
    else
        echo "起動に失敗しました。ログを確認してください: $LOG_FILE" >&2
        tail -n 20 "$LOG_FILE" >&2 || true
        return 1
    fi
}

stop() {
    if ! is_running; then
        echo "動いていません"
        rm -f "$PID_FILE"
        return 0
    fi
    local pid
    pid="$(cat "$PID_FILE")"
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true  # 見張りループごと止める
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
    done
    rm -f "$PID_FILE"
    echo "停止しました"
}

status() {
    if is_running; then
        echo "動いています(PID $(cat "$PID_FILE"))。http://$(hostname):$(port)/"
    else
        echo "止まっています"
    fi
    if crontab -l 2>/dev/null | grep -qF "$CRON_MARK"; then
        echo "自動起動: 登録済み"
    else
        echo "自動起動: 未登録(install で登録できます)"
    fi
}

# このアプリ以外のcronの行。読み込みを先に終えてから書き込む(同時に行うと既存の行が消えることがある)
other_cron_lines() {
    local current
    current="$(crontab -l 2>/dev/null || true)"
    if [[ -n "$current" ]]; then
        printf '%s\n' "$current" | grep -vF "$CRON_MARK" || true
    fi
}

write_crontab() {
    local backup="$RUN_DIR/crontab.backup"
    crontab -l >"$backup" 2>/dev/null || true  # 念のため変更前を保存
    printf '%s\n' "$1" | crontab -
}

install() {
    local line="@reboot sleep 20 && bash \"$SELF\" start $CRON_MARK"
    # 既存の登録(アップロード画面など)はそのまま残し、このアプリの行だけを入れ替える
    write_crontab "$( (other_cron_lines; echo "$line") )"
    echo "自動起動を登録しました(再起動の20秒後に起動)"
    start
}

uninstall() {
    stop
    write_crontab "$(other_cron_lines)"
    echo "自動起動の登録を外しました"
}

update() {
    cd "$REPO_DIR"
    git pull --ff-only
    stop
    start
}

case "${1:-}" in
    start) start ;;
    stop) stop ;;
    restart) stop; start ;;
    status) status ;;
    install) install ;;
    uninstall) uninstall ;;
    update) update ;;
    log) tail -n "${2:-50}" "$LOG_FILE" ;;
    _supervise) supervise ;;
    *) sed -n '2,12p' "$SELF" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
