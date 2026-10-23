# プロジェクト構成メモ

このリポジトリは、公開サイト・データ更新・トレーナーガイド取り込みを同居させている。公開に必要なものとローカル作業専用のものを区別し、移動や削除の判断基準にする。

## 普段使う場所

| 場所 | 役割 | 扱い |
| --- | --- | --- |
| `frontend/` | Next.jsの公開サイト。Vercelはここをビルドする。 | **移動しない** |
| `frontend/app/` | 画面のレイアウト・状態管理。 | 公開サイトの実装 |
| `frontend/src/components/` | サポカ検索、編成、スキル表示。 | 公開サイトの実装 |
| `frontend/src/data/` | 公開時に直接読むカード・レース・スキルJSON。 | 公開データの正本 |
| `frontend/src/lib/` | 因子周回・本育成のスキル判定と採点。 | 公開サイトの計算 |
| `.github/workflows/` | GameTora更新PRを作るGitHub Actions。 | 自動更新の設定 |

## ローカルのデータ作業で使う場所

| 場所 | 役割 |
| --- | --- |
| `backend/tools/` | GameTora取り込み、Gemini抽出、CSV確認、レースJSON生成、ラズパイ同期。 |
| `backend/data/guide_import/` | トレーナーガイドから抽出したCSVと確認済みCSV。 |
| `backend/data/race_events/` | レースイベント単位の入力データ。 |
| `backend/data/import/` | GameTora取り込み用の説明・中間データ。 |
| `frontend/prisma/` | スキル確認用のPrismaスキーマと履歴。公開サイトでは使わない。 |
| `frontend/scripts/` | Prismaへの取り込み・書き出し・レビュー補助。 |
| `tools/screenshot/` | Windowsでのスクショ撮影とラズパイ転送。 |

## 旧構成・比較用データ

次のファイルは現行の公開サイトでは使わない。削除はせず、実際に使わないと確認できた段階で `archive/` へ移す候補とする。

| 候補 | 以前の役割 |
| --- | --- |
| `backend/main.py` | FastAPIによるカード・レース・編成API。現在の静的サイトは使わない。 |
| `backend/saved_deck.json` | FastAPI用の編成保存データ。 |
| `backend/parse_screenshot.py` | EasyOCRによる旧スクショ抽出。現在はGemini抽出を使う。 |
| `backend/data/cards.json` | 旧カードJSONのスナップショット候補。公開用の正本は `frontend/src/data/cards.json`。 |
| `frontend/src/data/race_data.pi-preview.json` | 取り込み前のプレビューJSON。 |
| `frontend/src/data/race_data.pi-preview.clean.json` | 上記プレビューの確認済み版。 |

## 自動生成物

以下はローカルで作り直せる。Gitへ追加・移動・手編集はしない。

- `frontend/node_modules/` — `npm ci` で再作成
- `frontend/.next/` — `npm run dev` / `npm run build` で再作成
- `frontend/out/` — `npm run build` で再作成する静的出力
- `__pycache__/`、`*.pyc`、`backend/uploads/` — 実行時生成物

## 整理の進め方

1. この表を基準に、普段触る場所を `frontend/` と `backend/tools/` に絞る。
2. 旧構成はまず `archive/legacy-fastapi/` と `archive/legacy-ocr/` に**移動**する。削除はしない。
3. 比較用JSONは、再利用の必要がなければ `archive/data-previews/` に移す。
4. 移動ごとにREADME・スクリプト・GitHub Actionsの参照先を検索し、ローカルビルドを通す。

公開サイトのパスを変える整理は、Vercel設定とGitHub Actionsを同時に変更する必要があるため、この段階では行わない。
