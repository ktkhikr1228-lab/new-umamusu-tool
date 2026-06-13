# new-umamusu-tool

ウマ娘の因子周回向けに、レース条件ごとのおすすめスキルを見ながらサポートカード編成を組むためのWebツールです。

最終更新: 2026-06-13

## 現在の状態

- 公開先: https://new-umamusu-tool.vercel.app/
- 主な画面: サポカ検索、目標条件、スキル確認、現在の編成
- 対象ユーザー: 初心者から中級者を優先
- 保存機能: ユーザー別保存はまだ保留中
- お問い合わせ: Googleフォームへのリンクを設置

## 現在できること

- レース条件と脚質を選ぶ
- 超おすすめスキル / おすすめスキルを確認する
- サポカ名、キャラ名、カード名、スキル名で検索する
- カードタイプで絞り込む
- 不足スキルを持つカードを優先して並び替える
- 6枚のサポカ編成を画面上で組む
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
| Backend | FastAPI。ローカル検証や補助API用 |
| Hosting | Vercel |
| Data | `frontend/src/data/*.json` |

## ディレクトリ

```text
frontend/
  app/                  Next.js app router
  app/api/              Vercel上で使う簡易API
  src/components/       UIコンポーネント
  src/data/             サポカ、レース条件、除外スキルのJSON
  src/lib/              型定義と共通ロジック

backend/
  main.py               FastAPI
  tools/                GameToraデータ取り込みなどの補助スクリプト
  data/import/          手動取得したGameTora JSONの置き場
```

## ローカル起動

フロントだけ確認する場合:

```powershell
cd frontend
npm install
npm run dev
```

開くURL:

```text
http://localhost:3000
```

FastAPIも使う場合:

```powershell
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

必要に応じてフロント側で `NEXT_PUBLIC_API_URL` を設定します。

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

## 今後やりたいこと

- スマホ表示の調整
- レース条件と脚質データの拡充
- スクショからスキル表へ取り込む運用の整理
- お問い合わせ内容をもとにUI/UXを改善
- ユーザー別保存機能の優先度を再検討

