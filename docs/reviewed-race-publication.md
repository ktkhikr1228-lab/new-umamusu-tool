# 確認済みレーススキルから公開PRを作る

## 構成

Vercelと公開URLは変更しません。確認済みCSVからリクエストを生成し、GitHub Actionsが公開JSONの差分・ビルドを確認してPRを作ります。人がPRをマージし、Vercelのmain自動デプロイで公開します。

- 自動マージ・自動承認はありません。
- Gemini抽出直後のdraft行、rejected行は公開しません。
- この段階はCSV/CLIとActionsの基盤です。管理サイトの公開ボタン、スマホでの修正画面、Discord通知は未接続です。
- Actionsがmainに追加されるまでは実送信できません。

## 1. 確認済みCSVから送信データを作る

リポジトリのルートで実行します。既存CSVは読み取るだけです。

```bash
python backend/tools/publish_reviewed_race_data.py prepare \
  --input /path/to/reviewed.csv \
  --event 2026-09_CM \
  --output /tmp/reviewed-request.json
```

CSVには `race,strategy,tier,skill,status` が必要です。例：

```csv
race,strategy,tier,skill,status
東京 芝 1800m,先行,recommended,末脚,ready
```

`ready` / `approved` / `ok` / `公開` / `確認済み` の行だけを採用します。抽出結果を一括でreadyに変更せず、画像と照合してから確認済みにしてください。0行の場合、未知スキル、条件不備、同じスキルの区分競合はエラーです。

スキル名はマスターで照合します。○・◯・〇は同一視し、◎は別扱いです。本当に新しい名前がマスターにない場合、先にスキルマスターを確認・更新する必要があります。未知の名前を推測で公開しません。

## 2. 送信前のドライラン

```bash
python backend/tools/dispatch_reviewed_race_data.py \
  --input /tmp/reviewed-request.json --dry-run
```

ドライランは認証ファイルを読まず、通信しません。件数と送信サイズを確認できます。送信JSONは48KB以下、1リクエスト最大4,000行です。

## 3. PR作成を依頼する

```bash
python backend/tools/dispatch_reviewed_race_data.py \
  --input /tmp/reviewed-request.json
```

既存の `~/.config/uma-tool/github_token` を使って `publish-reviewed-race-data.yml` を起動します。必要なのは対象リポジトリへのActions起動権限です。ラズパイのトークンで直接PRを作成しません。認証値はコマンド引数やリポジトリに入れないでください。

HTTP 204は受付のみを示します。スクリプトが表示するActionsページで検証・ビルド・PR作成の完了を確認してください。403ならActions書き込み権限、404ならワークフローがmainに追加されているかを確認します。GitHubリポジトリ側でActionsからのPR作成が許可されている必要があります。

## ラズパイで使う場合

2つのPythonスクリプトを同じディレクトリへ配置します。画像・CSV・DBは移動しません。スキルマスターはラズパイの既存ファイルを明示します。

```bash
cd /home/katao/uma-tool-automation/publication
python3 publish_reviewed_race_data.py \
  --master /home/katao/uma-guide-data/skill_master.json prepare \
  --input /path/to/reviewed.csv --event 2026-09_CM \
  --output /tmp/reviewed-request.json
python3 dispatch_reviewed_race_data.py --input /tmp/reviewed-request.json --dry-run
```

Actions側でもmainのスキルマスターを使って再検証します。ラズパイ側だけが新しいマスターでも、mainで未確認の名前は公開できません。

## 差分の扱い

- 新しいレース名は `race_data.json` のキーとして追加され、既存の公開画面の選択肢へ表示されます。
- 無関係なレース、脚質、スキルは削除しません。
- 明示的に確認したスキルの区分変更だけは、反対の区分から移動します。
- 現行の公開データはイベント別ではなく「競馬場・馬場・距離・脚質」の単位です。季節が異なるイベントでも同じ条件は同じ欄に追加されます。季節スキルなどを全面入れ替えしたい場合は、追加だけの今回の処理ではなく別途レビューが必要です。
- 一般的な削除・名前修正で旧スキルを削除する操作は対象外です。誤った公開済みスキルを取り除く場合は別のレビューが必要です。
- 同じイベントは `data/reviewed-race-<event>` の同じPRへまとめます。前回の未マージ依頼を復元してから追加し、前回分を失わないようにします。
- 依頼内容は `backend/data/reviewed_race_requests/<event>.json` に監査用として残します。画像、認証情報、ローカルファイルパスは含めません。
- 公開JSONに差分がなければPRを新規作成・更新しません。

## 検証状況

- 公開前の拒否条件、既存データ保持、区分移動、未マージ分の保持、再送時の差分ゼロ、通信なしのドライランをテスト。
- フロントエンドの静的ビルドを確認。
- mainへのマージ前のため、実際のActions起動・データPR作成・Vercelデプロイは未検証です。
