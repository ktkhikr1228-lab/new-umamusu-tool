# new-umamusu-tool

ウマ娘の因子周回向けに、レース条件ごとの有効スキルを見ながらサポートカード編成を組むためのWebツールです。

最終更新: 2026-11-08

## 現在の状態

- 公開先: https://new-umamusu-tool.vercel.app/
- 主な画面: サポカ検索、目標条件、スキル確認、現在の編成
- 対象ユーザー: 初心者から中級者を優先
- 保存機能: ブラウザのlocalStorageで編成を3スロット保存。別端末との共有には未対応
- お問い合わせ: Googleフォームへのリンクを設置
- 補助環境: Raspberry Pi 3B+でスクショ取り込み、Gemini抽出、Discord通知を試験運用中

## 現在できること

- レース条件と脚質を選ぶ
- 超おすすめスキル / おすすめスキルを確認する
- サポカ名、キャラ名、カード名、スキル名で検索する
- カードタイプで絞り込む
- 不足スキルを持つカードを優先して並び替える
- 6枚のサポカ編成を画面上で組む
- 同じブラウザで編成を保存・復元する
- 因子周回 / 本育成のモードを切り替える

## 因子周回モードの扱い

因子周回では、継承で狙う優先度が低いものを表示と計算から外します。

- `◎` スキルは除外
- GameTora上で通常スキル以外として扱われるスキルは除外
- 検索、スコア計算、目標スキル表示、編成内スキル表示に同じルールを適用

本育成モードでは、金スキルなども含めた確認を想定しています。

## 技術構成

| 領域 | 内容 |
| --- | --- |
| Frontend | Next.js 16 / React 19 / TypeScript / Tailwind CSS |
| API | 公開サイトは静的構成。Piの管理GUIとローカル編集用サーバは別途運用 |
| Database | Prisma / PostgreSQL。ラズパイの編集用RaceSkillテーブルを管理。公開サイトはDB不要 |
| Backend | FastAPI。ローカル検証や補助スクリプト用 |
| Hosting | Vercel |
| Data | `frontend/src/data/*.json` |
| Automation | Raspberry Pi / Tailscale / Discord Webhook / Gemini API |

## ディレクトリ

```text
frontend/
  app/                  Next.js app router
  app/api/              API関連コード(公開サイトは静的エクスポート)
  prisma/               Prisma schema
  scripts/              Prisma取り込みやエクスポート補助
  src/components/       UIコンポーネント
  src/data/             サポカ、レース条件、除外スキルのJSON
  src/lib/              型定義と共通ロジック

backend/
  main.py               FastAPI
  tools/                GameTora、トレーナーガイド、Pi同期などの補助スクリプト
  data/import/          手動取得したGameTora JSONの置き場
  data/guide_import/    トレーナーガイド抽出CSVと確認済みCSV
```

画像ファイルそのものはGitHubに入れません。ローカル、Google Drive、またはラズパイ側の保存ディレクトリで管理します。

## ローカル起動

フロントだけ確認する場合:

```powershell
cd C:\Users\katao\uma-tool-workspace\current\new-umamusu-tool\frontend
npm install
npm run dev
```

開くURL:

```text
http://localhost:3000
```

FastAPIも使う場合:

```powershell
cd C:\Users\katao\uma-tool-workspace\current\new-umamusu-tool\backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

必要に応じてフロント側で `NEXT_PUBLIC_API_URL` を設定します。

## 編成保存

編成はブラウザのlocalStorageに自動保存します(3スロット、切り替え式)。サーバもDBも使わないため、サイト全体が完全静的です。

- 保存先キー: `uma-tool-decks-v1`(カードIDの配列×3スロット)
- 旧形式 `uma-tool-deck-v1` は初回アクセス時に編成1へ自動移行
- 保存はそのブラウザ限定。別端末との共有はできない(必要になったら再検討)

## 確認済みスキル・レース情報の公開PR

確認済みCSVから公開リクエストを作り、GitHub Actionsで検証・ビルドしたうえでPRを作成できます。公開サイトは既存のVercelを継続利用します。自動マージは行いません。

手順と制約は [確認済みレーススキルの公開](docs/reviewed-race-publication.md) を参照してください。管理サイトの公開ボタンとの接続は今後の作業です。

## ホスティング / デプロイ

`frontend` は `output: "export"` の静的エクスポート構成です。`npm run build` で `out/` に静的サイトが生成され、Cloudflare Pages / Vercel / GitHub Pages などにそのまま置けます。

Cloudflare Pagesの場合:

1. Pagesでこのリポジトリを接続
2. ルートディレクトリ: `frontend`、ビルドコマンド: `npm run build`、出力: `out`
3. デプロイ後、カスタムドメインを割り当て(任意)

以降はmainへのpushごとに自動デプロイされます。

## データ更新

サポカデータはGameTora由来のJSONを取り込んで更新します。

詳しい手順:

- `backend/data/import/README.md`

主な対象:

- `support-cards`
- `skills`
- `training_events/ssr`
- `training_events/sr`

レース条件ごとのスキルデータは、現在は `frontend/src/data/race_data.json` を参照します。

## トレーナーガイド画像の取り込み

ゲーム内トレーナーガイドのスクショから、レース条件ごとのスキルCSVを作ります。

基本の流れ(推奨: DB経由):

```text
スクショ(ホットキーで撮影・転送 → tools/screenshot/ 参照)
  -> Gemini APIで抽出(複数画像/1リクエスト + skill_master自動補正)
  -> npm run skills:import でRaceSkillテーブルへ
  -> レビューページで画像と照合し、要確認行を修正・確認済みにする
  -> 確認済みCSVから公開リクエストを生成
  -> GitHub Actionsで検証・ビルドしてPR作成
  -> 人がマージし、Vercelで公開
```

### スクショの撮影・転送(半自動)

`tools/screenshot/` のAutoHotkeyスクリプトを常駐させ、撮影は **F8**、Ctrl+Alt+1〜4は脚質切替、Ctrl+Alt+5は超おすすめ、Ctrl+Alt+6はおすすめへの切替です。F8でキャプチャ→ローカル保存→ラズパイinboxへの転送を行います。イベント名は同じフォルダの `current_event.txt` に設定します(例: `2026-11_LOH`)。ゲーム内のタブとは自動連動しないため、手動で合わせてください。撮影だけではGemini抽出は実行しません。詳細は `tools/screenshot/README.md`。

### 抽出の改善点

`extract_trainer_guide.py` は以下に対応しています:

- `--batch-size`(既定4): 複数画像を1回のGemini呼び出しにまとめ、API消費を削減
- skill_master照合: 表記ゆれ(半角!等)や軽微な誤字を自動修正し `auto_fix` をmemoに記録。マスターに無い名前は `unknown_skill:要確認` を付与

### 旧フロー(CSV手動チェック)

```text
スクショ画像
  -> Gemini APIで抽出
  -> backend/data/guide_import/extracted/*.csv
  -> backend/tools/check_extracted_skills.py で表記ゆれ確認
  -> backend/data/guide_import/checked/race_skills_checked.csv
  -> backend/tools/build_race_data.py
  -> frontend/src/data/race_data.json
```

ローカルで確認する例:

```powershell
cd C:\Users\katao\uma-tool-workspace\current\new-umamusu-tool
python backend\tools\check_extracted_skills.py `
  --input-glob "backend\data\guide_import\extracted\*.csv"

python backend\tools\check_extracted_skills.py `
  --input-glob "backend\data\guide_import\extracted\*.csv" `
  --write-fixed backend\data\guide_import\checked\race_skills_checked.csv

python backend\tools\build_race_data.py `
  --input backend\data\guide_import\checked\race_skills_checked.csv `
  --output frontend\src\data\race_data.json `
  --include-draft
```

抽出結果は必ず人間が確認します。Geminiは便利ですが、超おすすめ / おすすめの混在や表記ゆれが起きるため、最終反映前の確認が必要です。

## Raspberry Pi運用

ラズパイは本番サイトを置く場所ではなく、運用補助の小さいサーバーとして使います。

主な役割:

- スクショ画像の受け取り
- Gemini APIによる画像抽出
- 抽出済みCSVの保存
- 古いスクショの整理
- Discordへの通知
- 公式ニュース監視とイベントフォルダ作成の補助
- GameToraスキルデータの更新監視。PiではJST 12:15・12:45・14:15・15:00に確認する運用へ変更済み。日本語スキルの追加・内容変更を通知し、外国語のみの変更や削除のみでは通知しない
- GitHub Actionsの定期実行はmainのワークフロー設定に従う。README更新時点ではJST 12:15・15:00・18:00・21:00。Piと同じ時刻への変更は[PR #65](https://github.com/ktkhikr1228-lab/new-umamusu-tool/pull/65)で別途確認する
- スキル修正管理用PostgreSQL(RaceSkillテーブル)のホスト

接続:

```powershell
ssh katao@uma-pi
```

ラズパイ側の主な場所:

```text
/home/katao/uma-tool-automation
/home/katao/uma-guide-data/screenshots
/home/katao/uma-guide-data/extracted
```

GUI:

```text
http://uma-pi:8080
```

GUIでできること:

- スクショアップロード
- 競馬場、馬場、距離、脚質を選んで保存
- 保存済み画像の抽出前に対象件数・スキップ件数・APIリクエスト数の見積もりを確認
- 確認画面からGemini抽出を開始(現在の主モデル: `gemini-3.5-flash-lite`)
- 同じ画像の再抽出を抑制し、運用ページ `/operations` で処理状態を確認
- 抽出済みCSV一覧の確認
- イベント別フォルダの確認

Tailscale経由で、自宅外からも同じGUIへアクセスできます。名前解決できない場合は `http://100.87.114.18:8080/` を使います。スマホも同じTailscaleネットワークに接続してください。外部へ一般公開はしません。スマホ向けスキル修正画面と管理GUIの公開ボタンは未接続です。

## Piからローカルへ同期する流れ

ラズパイで作った抽出CSVは、そのまま本番反映せず、ローカルへコピーして確認します。

```text
Raspberry Pi extracted CSV
  -> local backend/data/guide_import/extracted_pi_preview/
  -> check_extracted_skills.py
  -> race_skills_checked_pi_preview_clean.csv
  -> race_data.pi-preview.clean.json
  -> 問題なければ race_data.json へ反映
```

この流れは試験運用中です。プレビュー用JSONは確認目的で、本番データとは分けて扱います。

## Prismaによるスキル修正管理

抽出済みスキルはPrismaの `RaceSkill` テーブルで管理できます。DBは編集専用で、公開データは従来どおり `race_data.json` の静的JSONです(DBが落ちてもサイトは動く)。

```text
Gemini抽出CSV
  -> npm run skills:import  (RaceSkillテーブルへ取り込み)
  -> レビューページで画像と見比べて修正(下記)
  -> 確認した行をready化
  -> 確認済みCSV -> 公開リクエスト -> Actions検証・ビルド -> PR
  -> 人がマージ -> Vercelで公開
```

### レビューページでの確認・修正(推奨)

スクショと抽出結果を横並びで見比べ、その場で修正してDBへ適用できます。

```powershell
# 1. レビューページ生成(リポジトリルートで)
python backend\tools\build_review_page.py `
  --csv "backend\data\guide_import\extracted_pi_preview\中山_芝_3600m_1_nige.csv" `
  --images-dir "$env:USERPROFILE\uma-shots\2026-07_CM\1_nige" `
  --output review_nige.html

# 2. 適用サーバを起動(frontendで、DATABASE_URL設定済みで)
node scripts/review-server.mjs
```

review_nige.htmlをブラウザで開き、赤帯(unknown_skill)を画像と見比べて名前修正 or「除外」チェック →「DBに適用」ボタン。修正先が既に存在する場合はサーバが自動で除外(rejected)に切り替えるので、重複エラーは起きません。

対象レースのdraft行をすべて画像と照合した場合だけ、一括ready化します。未確認行が残っている場合は実行しません:

```powershell
node scripts/db-query.mjs 'update RaceSkill set status = ''ready'' where race = ''中山 芝 3600m'' and status = ''draft'''
```

### db-query(任意SQLの実行)

```powershell
node scripts/db-query.mjs 'select count(*) from RaceSkill'
node scripts/db-query.mjs --file fixes.sql
```

Prisma Studio(`npm run prisma:studio`)は閲覧・フィルタ用として使えますが、v7ではセル編集時にエラー理由が表示されないことがあるため、修正はレビューページかdb-query経由を推奨します。

### 編集用DB(ラズパイのPostgreSQL)

uma-piにPostgreSQLを立てて、PCからTailscale経由で接続します。

ラズパイ側(初回のみ):

```bash
sudo apt install postgresql
sudo -u postgres psql -c "CREATE USER uma WITH PASSWORD 'パスワード';"
sudo -u postgres psql -c "CREATE DATABASE uma_tool OWNER uma;"
# /etc/postgresql/*/main/postgresql.conf: listen_addresses = '*'
# /etc/postgresql/*/main/pg_hba.conf: Tailscale CGNAT帯を追加
#   host all uma 100.64.0.0/10 scram-sha-256
sudo systemctl restart postgresql
```

PC側(frontendディレクトリで):

```powershell
$env:DATABASE_URL="postgresql://uma:パスワード@uma-pi:5432/uma_tool"
npm run prisma:migrate -- --name add_race_skill   # 初回のみ
npm run skills:import -- --event 2026-07_CM ../backend/data/guide_import/extracted
npm run prisma:studio                             # ブラウザで確認・修正
npm run skills:export
```

### 運用メモ

- `skills:import` は既存行(同じ race / strategy / tier / skill)をスキップするので、Studioでの手修正は再取り込みで消えない
- `skills:export` は既定で `status = ready` の行のみを書き出し、JSONを丸ごと作り直す。`--include-draft` でdraftも含む、`--merge` で既存JSONへ追記、`--dry-run` で件数確認のみ
- statusの値: `draft`(未確認) / `ready`(公開OK) / `rejected`(誤認識など除外)
- DBはラズパイの編集用です。編成保存はlocalStorage、公開用はJSONなのでVercelからDB参照は不要

## 変更しやすくするためのメモ

よく変わりそうな場所:

| 変更したい内容 | 主なファイル |
| --- | --- |
| UI全体の見た目 | `frontend/app/globals.css` |
| 画面レイアウト | `frontend/app/page.tsx` |
| サポカカード表示 | `frontend/src/components/card-search-panel.tsx` |
| 編成スロット表示 | `frontend/src/components/deck-slot.tsx` |
| スキル表示 | `frontend/src/components/skill-list.tsx` |
| 因子周回 / 本育成の計算 | `frontend/src/lib/utils.ts` |
| サポカデータ | `frontend/src/data/cards.json` |
| レース条件データ | `frontend/src/data/race_data.json` |
| 因子周回で除外するスキル | `frontend/src/data/non_factor_skills.json` |
| トレーナーガイド抽出 | `backend/tools/extract_trainer_guide.py` |
| 抽出スキルの確認 | `backend/tools/check_extracted_skills.py` |
| レースデータ生成 | `backend/tools/build_race_data.py` |
| スキルDB取り込み/書き出し | `frontend/scripts/import-race-skills.mjs` / `export-race-data.mjs` |
| レビューページ生成 | `backend/tools/build_review_page.py` |
| レビュー適用サーバ | `frontend/scripts/review-server.mjs` |
| DBへの任意SQL実行 | `frontend/scripts/db-query.mjs` |
| スクショ半自動化 | `tools/screenshot/` |
| スキルマスター生成/照合 | `backend/tools/build_skill_master.py` |
| GameTora更新監視(ラズパイ) | `backend/tools/gametora_skills_watch.py` |
| Pi同期 | `backend/tools/sync_pi_guide_data.py` |

## 今後やりたいこと

- スマホ表示の調整
- レース条件と脚質データの拡充(2026年11月LOH: 京都 芝 3000mのスクショ収集中。公開済みではない)
- 東京 芝 2400m 旧データのtier重複の整理(再抽出 or 手修正)
- 公開先はVercelを継続利用。Cloudflare Pages等への移行は必要になった場合に検討
- 独自ドメインの取得と広告掲載の検討(収益はサーバ代の足し程度)
- ラズパイGUIで画像管理をしやすくする
- 更新完了通知や利用状況通知をDiscordへ送る
- お問い合わせ内容をもとにUI/UXを改善

既存の実装: 超/おすすめの見出しベース抽出、Prisma(レビューページ)での確認・修正、
スクショのホットキー半自動化、GameToraスキル更新監視、サイト完全静的化、編成3スロット化


公開データはイベント別ではなく競馬場・馬場・距離・脚質ごとに保持します。同条件の別イベントを追加すると既存データと統合されるため、季節スキルの全面入れ替えには別途レビューが必要です。
