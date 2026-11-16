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
    # PIDファイルは再起動後も残る。同じ番号を別のプログラムが使っていても「動いている」と誤解しないよう、中身も確かめる
    [[ -f "$PID_FILE" ]] || return 1
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null)"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -q "guide_app.sh _supervise"
}

port() {
    "$PYTHON" -c "import sys; sys.path.insert(0, '$APP_DIR/..'); from guide_app.config import load_config; print(load_config().port)" 2>/dev/null || echo 8090
}

# 落ちても立ち上げ直すループ(内部用)
supervise() {
    cd "$REPO_DIR"
    local wait=5 began
    while true; do
        # ログが大きくなりすぎたら空にする(起動に失敗し続けたときに、ディスクを埋めないため)
        if [[ -f "$LOG_FILE" ]] && (( $(stat -c %s "$LOG_FILE") > LOG_LIMIT_BYTES )); then
            cp -f "$LOG_FILE" "$LOG_FILE.1" && : >"$LOG_FILE"
        fi
        echo "[$(date '+%F %T')] 起動します"
        began=$(date +%s)
        "$PYTHON" -u tools/guide_app serve || true
        # すぐ落ちる状態が続くときは、待ち時間を5秒→最大10分まで延ばす。1分以上動いたら元に戻す
        if (( $(date +%s) - began >= 60 )); then wait=5; else wait=$(( wait * 2 > 600 ? 600 : wait * 2 )); fi
        echo "[$(date '+%F %T')] 停止しました。${wait}秒後に再起動します"
        sleep "$wait"
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
    kill -9 -- "-$pid" 2>/dev/null || true   # 止まらないときは強制終了(ポートを握ったまま残さない)
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
    local current status=0
    current="$(crontab -l 2>&1)" || status=$?
    if (( status != 0 )); then
        # 「まだ登録がない」以外の失敗で続けると、既存の登録を消してしまう
        if grep -qi "no crontab" <<<"$current"; then current=""; else echo "crontabを読めませんでした: $current" >&2; exit 1; fi
    fi
    if [[ -n "$current" ]]; then
        printf '%s\n' "$current" | grep -vF "$CRON_MARK" || true
    fi
}

write_crontab() {
    local backup="$RUN_DIR/crontab.backup.$(date +%Y%m%d-%H%M%S)"
    crontab -l >"$backup" 2>/dev/null || rm -f "$backup"  # 念のため変更前を保存(登録がなければ作らない)
    printf '%s\n' "$1" | crontab -
}

install() {
    local line="@reboot sleep 20 && bash \"$SELF\" start $CRON_MARK"
    # 既存の登録(アップロード画面など)はそのまま残し、このアプリの行だけを入れ替える
    local others
    others="$(other_cron_lines)"   # 読めなかったときはここで止まる(既存の登録を消さない)
    write_crontab "$(printf '%s\n%s' "$others" "$line" | sed '/^$/d')"
    echo "自動起動を登録しました(再起動の20秒後に起動)"
    start
}

uninstall() {
    stop
    local others
    others="$(other_cron_lines)"
    write_crontab "$others"
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
