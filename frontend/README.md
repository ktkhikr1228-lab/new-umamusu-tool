# Frontend

ウマ娘 因子周回サポカ編成ツールのNext.jsフロントエンドです。

## 現在の役割

- Vercelで公開するメインアプリ
- サポカ検索、レース条件選択、スキル表示、編成表示を担当
- `app/api/*` で静的JSONを返す簡易APIを提供
- FastAPIが無くてもVercel上で表示できる構成

## 起動

```powershell
npm install
npm run dev
```

```text
http://localhost:3000
```

別ポートで起動したい場合:

```powershell
npm run dev -- --port 3001
```

## コマンド

```powershell
npm run lint
npm run build
```

## 環境変数

通常は未設定で動きます。

FastAPIなど外部APIを使う場合だけ設定します。

```text
NEXT_PUBLIC_API_URL=http://localhost:8000
```

本番Vercelで `NEXT_PUBLIC_API_URL` が未設定の場合は、Next.js内の `/api/cards` と `/api/race-data` を使います。

## 主要ファイル

| 目的 | ファイル |
| --- | --- |
| メイン画面 | `app/page.tsx` |
| 全体スタイル | `app/globals.css` |
| サポカ検索 | `src/components/card-search-panel.tsx` |
| 編成スロット | `src/components/deck-slot.tsx` |
| スキル一覧 | `src/components/skill-list.tsx` |
| 型定義 | `src/lib/types.ts` |
| 共通ロジック | `src/lib/utils.ts` |
| サポカデータ | `src/data/cards.json` |
| レース条件データ | `src/data/race_data.json` |
| 因子周回除外スキル | `src/data/non_factor_skills.json` |

## モード差分

因子周回モード:

- `◎` スキルを表示と計算から除外
- 通常スキル以外を表示と計算から除外

本育成モード:

- 金スキルを含めた確認を想定

この判定は `src/lib/utils.ts` に集約しています。
