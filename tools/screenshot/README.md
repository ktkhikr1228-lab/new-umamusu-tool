# スクショ半自動化ツール

トレーナーガイドのスクショを「ホットキー1発でキャプチャ→保存→ラズパイ転送」するツール。
ゲームへの入力は一切自動化しない(タブ切り替え・スクロールは人間が行う)。

## 準備(初回のみ)

1. AutoHotkey v2 をインストール: https://www.autohotkey.com/
2. uma-piへの鍵認証を設定(パスワードなしでssh/scpできる状態にする):

   ```powershell
   ssh-keygen -t ed25519          # 既に鍵があればスキップ
   type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh katao@uma-pi "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
   ```

3. `current_event.txt` にイベント名を書く(例: `2026-09_CM`)

## 使い方

1. `uma_capture_hotkeys.ahk` をダブルクリック(タスクトレイに常駐、画面右上に現在の脚質を表示)
2. **撮影は F8 のみ**。ゲーム内の脚質タブ・区分を切り替えるときだけ以下を押す:

   | キー | 動作 |
   | --- | --- |
   | F8 | 現在の脚質で撮影(キャプチャ→保存→転送) |
   | Ctrl+Alt+1 | 脚質を「逃げ」に |
   | Ctrl+Alt+2 | 脚質を「先行」に |
   | Ctrl+Alt+3 | 脚質を「差し」に |
   | Ctrl+Alt+4 | 脚質を「追込」に |
   | Ctrl+Alt+5 | 区分を「超おすすめ」に |
   | Ctrl+Alt+6 | 区分を「おすすめ」に |
   | Ctrl+Alt+0 | 常駐終了 |

3. 流れの例: 逃げタブを開く → Ctrl+Alt+5 → F8(超おすすめ部分) → Ctrl+Alt+6 → F8(おすすめ部分) → 先行タブへ → Ctrl+Alt+2 → Ctrl+Alt+5 → …
4. 高いピッ2回=保存+転送成功。低いブー=転送失敗(ローカルには残っている)

## 撮り方

- 「超おすすめ」と「おすすめ」の境界を1枚で撮る必要はない
- それぞれの区分に切り替えてから、該当する範囲だけをF8で撮る
- 画面に見出しが無くても、現在の区分はホットキーで指定済みなので推測しない
- 撮り直すときは、そのイベントの該当脚質・区分フォルダだけを最初から撮り直す

## 保存先

- ローカル: `%USERPROFILE%\uma-shots\<イベント>\<脚質>\<区分>\`
- ラズパイ: `/home/katao/uma-guide-data/screenshots/inbox/<イベント>/<脚質>/<区分>/`
  (アップロードGUIと同じinbox構造なので、そのままGemini抽出に回せる)

## 転送後の流れ

ラズパイで抽出(またはアップロードGUI http://uma-pi:8080 から実行):

```bash
cd /home/katao/uma-tool-automation
python3 gemini_extract_uploaded.py --event 2026-07_CM --race "中山 芝 3600m" --strategy senkou
```

抽出はskill_master照合で表記ゆれを自動修正し、怪しい名前には `unknown_skill:要確認` が付く。
