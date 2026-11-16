; ウマ娘トレーナーガイドのスクショ半自動化ホットキー (AutoHotkey v2)
;
; 使い方(くわしくは同じフォルダの README.md):
;   1. AutoHotkey v2 をインストール (https://www.autohotkey.com/)
;   2. このファイルをダブルクリックで常駐開始。最初にイベント名の確認が出る
;   3. ゲームの画面を手前にして使うキー(ほかのアプリでは効かない):
;        F8       = 撮影
;        F9       = 次の枠へ(逃げ/超おすすめ → 逃げ/おすすめ → 先行/超おすすめ → … → 追込/おすすめ)
;        Shift+F9 = ひとつ前の枠へ
;   4. どのアプリでも効くキー:
;        Ctrl+Alt+1 = 逃げ    Ctrl+Alt+2 = 先行
;        Ctrl+Alt+3 = 差し    Ctrl+Alt+4 = 追込
;        Ctrl+Alt+5 = 超おすすめ    Ctrl+Alt+6 = おすすめ
;        Ctrl+Alt+0 = 常駐終了
;
; ゲームへの入力は一切しない。タブ切り替えとスクロールは人が行う。
; 画面右上に イベント名 / 脚質 / 区分 / この枠の枚数 / 未送信の枚数 を常時表示する。
;
; このファイルは「UTF-8(BOM付き)」で保存すること。BOMが無いと日本語が文字化けする。

#Requires AutoHotkey v2.0
#SingleInstance Force

CoordMode("ToolTip", "Screen")

ScriptDir := A_ScriptDir
EventFile := ScriptDir . "\current_event.txt"
ShotsRoot := EnvGet("USERPROFILE") . "\uma-shots"
PendingFile := ShotsRoot . "\pending_uploads.txt"
EventPattern := "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"

CurrentEvent := ""
CurrentStrategy := "nige"
CurrentTier := "super"
LastStatusText := ""
LastPendingCount := 0

StrategyOrder := ["nige", "senkou", "sashi", "oikomi"]
TierOrder := ["super", "recommended"]
StrategyLabels := Map("nige", "逃げ", "senkou", "先行", "sashi", "差し", "oikomi", "追込")
StrategyDirs := Map("nige", "1_nige", "senkou", "2_senkou", "sashi", "3_sashi", "oikomi", "4_oikomi")
TierLabels := Map("super", "超おすすめ", "recommended", "おすすめ")

; ---------------------------------------------------------------- 起動時の処理

ConfirmEvent()
ShowStatus()
SetTimer(ShowStatus, 2000)
ResendPending()

; ---------------------------------------------------------------- ホットキー

; F8 / F9 はゲームの画面が手前にあるときだけ。ほかのアプリではそのまま通る
#HotIf WinActive("UmamusumePrettyDerby_Jpn")
#MaxThreadsPerHotkey 4
F8::Capture()
#MaxThreadsPerHotkey 1
F9::NextStep()
+F9::PrevStep()
#HotIf

; 脚質・区分の切り替え(どのアプリでも効く)
^!1::SetStrategy("nige")
^!2::SetStrategy("senkou")
^!3::SetStrategy("sashi")
^!4::SetStrategy("oikomi")
^!5::SetTier("super")
^!6::SetTier("recommended")

; Ctrl+Alt+0 : 常駐終了
^!0::ExitApp()

; ---------------------------------------------------------------- イベント名

ReadEventFile() {
    global EventFile
    text := ""
    try {
        text := FileRead(EventFile, "UTF-8")
    } catch {
        text := ""
    }
    return Trim(text, " `t`r`n")
}

; 起動時にイベント名を見せて、確認または書き直してもらう
ConfirmEvent() {
    global CurrentEvent, EventFile, EventPattern
    saved := ReadEventFile()
    shown := saved
    Loop {
        prompt := "今回撮るイベント名を確認してください。`n`n"
        prompt .= "このままでよければ OK、違うときは書き直して OK。`n"
        prompt .= "(半角の英数字・ハイフン・アンダーバーだけ。例: 2026-11_CM)"
        ib := InputBox(prompt, "イベント名の確認", "w460 h200", shown)
        if (ib.Result != "OK") {
            MsgBox("イベント名を確認できなかったので終了します。", "スクショツール")
            ExitApp()
        }
        value := Trim(ib.Value, " `t`r`n")
        if RegExMatch(value, EventPattern) {
            break
        }
        MsgBox("イベント名に使えない文字があります。`n半角の英数字・ハイフン(-)・アンダーバー(_)だけで、64文字までです。`n例: 2026-11_CM", "スクショツール")
        shown := value
    }
    if (value != saved) {
        try {
            if FileExist(EventFile) {
                FileDelete(EventFile)
            }
            FileAppend(value . "`n", EventFile, "UTF-8-RAW")
        } catch {
            MsgBox("current_event.txt に書き込めませんでした。`n今回はこのまま「" . value . "」で撮影できますが、次の起動時にもう一度入力してください。", "スクショツール")
        }
    }
    CurrentEvent := value
}

; ---------------------------------------------------------------- 表示

CurrentLocalDir() {
    global ShotsRoot, CurrentEvent, CurrentStrategy, CurrentTier, StrategyDirs
    return ShotsRoot . "\" . CurrentEvent . "\" . StrategyDirs[CurrentStrategy] . "\" . CurrentTier
}

; いまの枠のフォルダにある画像の枚数
CountImages() {
    n := 0
    pattern := CurrentLocalDir() . "\*.png"
    Loop Files, pattern
    {
        n += 1
    }
    return n
}

; まだラズパイへ送れていない画像の枚数
CountPending() {
    global PendingFile, LastPendingCount
    if !FileExist(PendingFile) {
        LastPendingCount := 0
        return 0
    }
    text := ""
    try {
        text := FileRead(PendingFile, "UTF-8")
    } catch {
        ; 書き込み中で読めなかったときは前回の値のまま
        return LastPendingCount
    }
    n := 0
    Loop Parse, text, "`n", "`r"
    {
        if (Trim(A_LoopField) != "") {
            n += 1
        }
    }
    LastPendingCount := n
    return n
}

; 何番目の枠か(1〜8)。脚質と区分から毎回計算するので Ctrl+Alt キーともずれない
StepIndex() {
    global CurrentStrategy, CurrentTier, StrategyOrder
    s := 1
    for i, name in StrategyOrder {
        if (name = CurrentStrategy) {
            s := i
        }
    }
    t := (CurrentTier = "super") ? 1 : 2
    return (s - 1) * 2 + t
}

GoToStep(n) {
    global CurrentStrategy, CurrentTier, StrategyOrder, TierOrder
    CurrentStrategy := StrategyOrder[(n - 1) // 2 + 1]
    CurrentTier := TierOrder[Mod(n - 1, 2) + 1]
}

; 右上の常時表示
ShowStatus() {
    global CurrentEvent, CurrentStrategy, CurrentTier, StrategyLabels, TierLabels, LastStatusText
    if (CurrentEvent = "") {
        return
    }
    count := CountImages()
    pending := CountPending()
    text := "イベント: " . CurrentEvent . "`n"
    text .= StrategyLabels[CurrentStrategy] . " / " . TierLabels[CurrentTier] . " (" . StepIndex() . "/8)`n"
    if (count = 0) {
        text .= "この枠: ★まだ 0枚★"
    } else {
        text .= "この枠: " . count . "枚"
    }
    if (pending > 0) {
        text .= "`n未送信: " . pending . "枚(あとで自動で再送)"
    }
    text .= "`nF8 撮影 / F9 次へ / Shift+F9 戻る"
    if (text != LastStatusText) {
        LastStatusText := text
        ToolTip(text, A_ScreenWidth - 380, 8, 1)
    }
}

; 一時的なお知らせ(常時表示の下に数秒だけ出す)
Flash(msg, ms := 3500) {
    ToolTip(msg, A_ScreenWidth - 380, 130, 2)
    SetTimer(ClearFlash, -ms)
}

ClearFlash() {
    ToolTip(, , , 2)
}

; ---------------------------------------------------------------- 切り替え

SetStrategy(strategy) {
    global CurrentStrategy
    CurrentStrategy := strategy
    ShowStatus()
    SoundBeep(800, 80)
}

SetTier(tier) {
    global CurrentTier
    CurrentTier := tier
    ShowStatus()
    SoundBeep(900, 80)
}

; F9: 決まった順番で次の枠へ。最後では止まる(最初へは戻らない)
NextStep() {
    global CurrentStrategy, CurrentTier, StrategyLabels, TierLabels
    n := StepIndex()
    leftCount := CountImages()
    leftLabel := StrategyLabels[CurrentStrategy] . " / " . TierLabels[CurrentTier]
    if (n >= 8) {
        msg := "ここが最後の枠です(追込 / おすすめ)。全部撮り終わりました。"
        if (leftCount = 0) {
            msg .= "`n注意: この枠はまだ 0枚です。"
        }
        Flash(msg, 6000)
        SoundBeep(1000, 120)
        SoundBeep(750, 120)
        SoundBeep(500, 300)
        return
    }
    oldStrategy := CurrentStrategy
    GoToStep(n + 1)
    ShowStatus()
    msg := "次: " . StrategyLabels[CurrentStrategy] . " / " . TierLabels[CurrentTier]
    if (CurrentStrategy != oldStrategy) {
        msg .= "`nゲームの脚質タブも切り替えてください。"
    }
    if (leftCount = 0) {
        msg .= "`n注意: さっきの枠(" . leftLabel . ")は 0枚でした。"
    }
    Flash(msg)
    SoundBeep(1000, 80)
}

; Shift+F9: ひとつ前の枠へ
PrevStep() {
    global CurrentStrategy, CurrentTier, StrategyLabels, TierLabels
    n := StepIndex()
    if (n <= 1) {
        Flash("ここが最初の枠です(逃げ / 超おすすめ)。")
        SoundBeep(500, 200)
        return
    }
    GoToStep(n - 1)
    ShowStatus()
    Flash("戻る: " . StrategyLabels[CurrentStrategy] . " / " . TierLabels[CurrentTier])
    SoundBeep(700, 80)
}

; ---------------------------------------------------------------- 撮影・再送

PowerShellCommand() {
    global ScriptDir
    return 'powershell -NoProfile -ExecutionPolicy Bypass -File "' . ScriptDir . '\capture_upload.ps1"'
}

; F8: 撮影。撮影・保存の結果だけを待つ(転送は別プロセスが裏で行うので待たない)
Capture() {
    global CurrentEvent, CurrentStrategy, CurrentTier
    if (CurrentEvent = "") {
        return
    }
    ; 押した時点の枠を使う
    cmd := PowerShellCommand() . " -Strategy " . CurrentStrategy . " -Tier " . CurrentTier . " -Event " . CurrentEvent
    code := -1
    try {
        code := RunWait(cmd, , "Hide")
    } catch {
        Flash("撮影スクリプトを起動できませんでした。")
        SoundBeep(400, 400)
        return
    }
    if (code = 0) {
        ShowStatus()
    } else if (code = 3) {
        Flash("同じ画面です(保存していません)。`nスクロールしてからもう一度 F8 を押してください。", 5000)
    } else if (code = 4) {
        Flash("ゲームの画面が見つかりません。", 5000)
    } else if (code = 5) {
        Flash("イベント名が正しくありません。ツールを起動し直してください。", 5000)
    } else {
        Flash("撮影に失敗しました(コード " . code . ")。", 5000)
    }
}

; 起動時: 前回までに送れなかった画像を裏で再送する(待たない)
ResendPending() {
    global PendingFile
    if !FileExist(PendingFile) {
        return
    }
    try {
        Run(PowerShellCommand() . " -ResendOnly", , "Hide")
    } catch {
        Flash("再送を開始できませんでした。")
    }
}
