# new-umamusu-tool

ウマ娘の因子周回向けに、レース条件ごとの有効スキルを見ながらサポートカード編成を組むためのWebツールです。

最終更新: 2026-07-02

## 現在の状態

- 公開先: https://new-umamusu-tool.vercel.app/
- 主な画面: サポカ検索、目標条件、スキル確認、現在の編成
- 対象ユーザー: 初心者から中級者を優先
- 保存機能: Prisma + PostgreSQLで匿名IDごとの編成保存に対応。`DATABASE_URL` 未設定時は表示中心
- お問い合わせ: Googleフォームへのリンクを設置
- 補助環境: Raspberry Pi 3B+でスクショ取り込み、Gemini抽出、Discord通知を試験運用中

## 現在できること

- レース条件と脚質を選ぶ
- 超おすすめスキル / おすすめスキルを確認する
- サポカ名、キャラ名、カード名、スキル名で検索する
- カードタイプで絞り込む
- 不足スキルを持つカードを優先して並び替える
- 6枚のサポカ編成を画面上で組む
- DB設定済み環境では編成を保存・復元する
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
| API | Next.js Route Handlers |
| Database | Prisma / PostgreSQL。現在は編成保存用。スキル修正管理への拡張を検討中 |
| Backend | FastAPI。ローカル検証や補助スクリプト用 |
| Hosting | Vercel |
| Data | `frontend/src/data/*.json` |
| Automation | Raspberry Pi / Tailscale / Discord Webhook / Gemini API |

## ディレクトリ

```text
frontend/
  app/                  Next.js app router
  app/api/              Vercel上で使うAPI
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
cd C:\tmp\new-umamusu-tool\frontend
npm install
npm run dev
```

開くURL:

```text
http://localhost:3000
```

FastAPIも使う場合:

```powershell
cd C:\tmp\new-umamusu-tool\backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

必要に応じてフロント側で `NEXT_PUBLIC_API_URL` を設定します。

## 編成保存

編成保存はNext.jsの `/api/deck` で扱います。ブラウザに匿名IDを作り、そのIDごとに1つの編成を保存します。

保存を有効にするにはPostgreSQLの接続文字列を `DATABASE_URL` に設定します。

```powershell
cd C:\tmp\new-umamusu-tool\frontend
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:PORT/DATABASE"
npm run prisma:migrate -- --name init
npm run dev
```

本番DBに既存マイグレーションを適用する場合:

```powershell
cd C:\tmp\new-umamusu-tool\frontend
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:PORT/DATABASE"
npm run prisma:deploy
```

Vercel本番で保存を使う場合も、同じ `DATABASE_URL` を環境変数に追加します。`DATABASE_URL` が未設定でもカード検索やレース条件表示は動きますが、保存ボタンは失敗します。

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

基本の流れ:

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
cd C:\tmp\new-umamusu-tool
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

接続:

```powershell
ssh uma-pi
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
- 保存済み画像からGemini抽出
- 抽出済みCSV一覧の確認
- イベント別フォルダの確認

Tailscale経由で、自宅外からも同じGUIへアクセスする想定です。外部へ一般公開はしません。

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

## Prismaの今後の使い道

現在のPrismaは主に編成保存用です。今後は次の用途に広げる可能性があります。

- 抽出済みスキルの確認状態管理
- 誤認識スキルの修正辞書
- 超おすすめ / おすすめの手動修正
- レース条件ごとのスキル履歴管理
- 管理画面からのデータ修正

毎月のレース更新をスムーズにするには、`race_data.json` を直接編集するより、Prisma上で確認・修正してからJSONへエクスポートする流れが有力です。

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
| Pi同期 | `backend/tools/sync_pi_guide_data.py` |

## 今後やりたいこと

- スマホ表示の調整
- レース条件と脚質データの拡充
- 超おすすめ / おすすめを画像段階で分けて抽出する
- Gemini抽出結果をPrismaで確認・修正できるようにする
- 公式ニュースから次回イベント候補を検知して通知する
- ラズパイGUIで画像管理をしやすくする
- 更新完了通知や利用状況通知をDiscordへ送る
- お問い合わせ内容をもとにUI/UXを改善
