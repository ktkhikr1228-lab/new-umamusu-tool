; ウマ娘トレーナーガイドのスクショ半自動化ホットキー (AutoHotkey v2)
;
; 使い方:
;   1. AutoHotkey v2 をインストール (https://www.autohotkey.com/)
;   2. このファイルをダブルクリックで常駐開始(開始時は「逃げ」モード)
;   3. 撮影は F8 だけ。脚質を切り替えるときだけ Ctrl+Alt+1〜4 を押す:
;        Ctrl+Alt+1 = 逃げ    Ctrl+Alt+2 = 先行
;        Ctrl+Alt+3 = 差し    Ctrl+Alt+4 = 追込
;   4. ゲーム内でタブを切り替えたら同じ脚質に合わせ、
;      スクロールしながら F8 を押していく
;
;   イベント名は同フォルダの current_event.txt に書く(例: 2026-07_CM)。
;
; 画面右上に現在の脚質が常時表示される。
; 音の意味: 高いピッ=保存成功 / さらに高いピッ=転送成功 / 低いブー=転送失敗

#Requires AutoHotkey v2.0

ScriptDir := A_ScriptDir
CurrentStrategy := "nige"
StrategyLabels := Map("nige", "逃げ", "senkou", "先行", "sashi", "差し", "oikomi", "追込")

ShowStrategy() {
    global CurrentStrategy, StrategyLabels
    ToolTip("脚質: " . StrategyLabels[CurrentStrategy] . " (F8で撮影)", A_ScreenWidth - 260, 8, 1)
}

SetStrategy(strategy) {
    global CurrentStrategy
    CurrentStrategy := strategy
    ShowStrategy()
    SoundBeep(800, 80)
}

Capture() {
    global CurrentStrategy, ScriptDir
    ps1 := ScriptDir . "\capture_upload.ps1"
    Run('powershell -NoProfile -ExecutionPolicy Bypass -File "' . ps1 . '" -Strategy ' . CurrentStrategy, , "Hide")
}

; 撮影(ワンキー)
F8::Capture()

; 脚質切り替え
^!1::SetStrategy("nige")
^!2::SetStrategy("senkou")
^!3::SetStrategy("sashi")
^!4::SetStrategy("oikomi")

; Ctrl+Alt+0 : 常駐終了
^!0::ExitApp()

; 起動時に現在の脚質を表示
ShowStrategy()
