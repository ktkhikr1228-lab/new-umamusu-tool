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

3. `current_event.txt` にイベント名を書く(例: `2026-07_CM`)

## 使い方

1. `uma_capture_hotkeys.ahk` をダブルクリック(タスクトレイに常駐、画面右上に現在の脚質を表示)
2. **撮影は F8 のみ**。脚質を切り替えるときだけ以下を押す(ゲーム内のタブ切り替えと合わせる):

   | キー | 動作 |
   | --- | --- |
   | F8 | 現在の脚質で撮影(キャプチャ→保存→転送) |
   | Ctrl+Alt+1 | 脚質を「逃げ」に |
   | Ctrl+Alt+2 | 脚質を「先行」に |
   | Ctrl+Alt+3 | 脚質を「差し」に |
   | Ctrl+Alt+4 | 脚質を「追込」に |
   | Ctrl+Alt+0 | 常駐終了 |

3. 流れの例: 逃げタブを開く → F8連打(スクロールしつつ) → ゲームで先行タブへ → Ctrl+Alt+2 → F8連打 → …
4. 高いピッ2回=保存+転送成功。低いブー=転送失敗(ローカルには残っている)

## 撮り方のコツ(tier判定の精度を上げる)

- 各脚質、**一番上から順に**スクロールしながら撮る(撮影順=スクロール順が前提)
- **「おすすめスキル」の見出しが画面内に入る位置で必ず1枚撮る**(超→おすすめの境界の証拠になる)
- 画面の重なりは気にしなくてよい(重複スキルは抽出時に自動でまとまる)
- 撮り直すときは、その脚質のフォルダの画像を消してから最初から撮り直す(順序が崩れると判定を誤る)

## 保存先

- ローカル: `%USERPROFILE%\uma-shots\<イベント>\<脚質>\`
- ラズパイ: `/home/katao/uma-guide-data/screenshots/inbox/<イベント>/<脚質>/`
  (アップロードGUIと同じinbox構造なので、そのままGemini抽出に回せる)

## 転送後の流れ

ラズパイで抽出(またはアップロードGUI http://uma-pi:8080 から実行):

```bash
cd /home/katao/uma-tool-automation
python3 gemini_extract_uploaded.py --event 2026-07_CM --race "中山 芝 3600m" --strategy senkou
```

抽出はskill_master照合で表記ゆれを自動修正し、怪しい名前には `unknown_skill:要確認` が付く。
