# Frontend

ウマ娘 因子周回サポカ編成ツールのNext.jsフロントエンドです。

## 現在の役割

- 静的エクスポート(`output: "export"`)で公開するメインアプリ
- サポカ検索、レース条件選択、スキル表示、編成表示(3スロット)を担当
- データはビルド時に `src/data/*.json` から焼き込み。サーバ処理なし
- 編成は3スロットをlocalStorageに自動保存(サーバ・DB不要)
- Prisma(schema/scripts)はスキルデータ編集用。本番サイトからは使わない

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
npm run build        # out/ に静的サイトを出力
npm run prisma:studio    # 編集用DB(ラズパイ)の確認・修正
npm run skills:import    # 抽出CSV -> RaceSkillテーブル
npm run skills:export    # RaceSkillテーブル -> race_data.json
```

## 環境変数

サイト本体は環境変数なしで動きます。

スキルデータ編集(skills:*、prisma:*)を使うときだけ、編集用DBの接続先を設定します。

```text
DATABASE_URL=postgresql://uma:PASSWORD@uma-pi:5432/uma_tool
```

## デプロイ

`npm run build` で `out/` に静的ファイルが生成されます。Cloudflare Pages / Vercel / GitHub Pages などの静的ホスティングにそのまま置けます。

Cloudflare Pagesの場合: ビルドコマンド `npm run build`、出力ディレクトリ `out`。

## 主要ファイル

| 目的 | ファイル |
| --- | --- |
| メイン画面 | `app/page.tsx` |
| Prisma設定(編集用DB) | `prisma/schema.prisma` |
| スキルDB取り込み/書き出し | `scripts/import-race-skills.mjs`, `scripts/export-race-data.mjs` |
| 全体スタイル | `app/globals.css` |
| サポカ検索 | `src/components/card-search-panel.tsx` |
| 編成スロット | `src/components/deck-slot.tsx` |
| スキル一覧 | `src/components/skill-list.tsx` |
| 型定義 | `src/lib/types.ts` |
| 共通ロジック | `src/lib/utils.ts` |
| サポカデータ | `src/data/cards.json` |
| レース条件データ | `src/data/race_data.json` |
| 因子周回除外スキル | `src/data/non_factor_skills.json` |
| 金スキルから下位スキルへの対応 | `src/data/factor_skill_aliases.json` |
| 全スキルマスター | `src/data/skill_master.json` |

## モード差分

因子周回モード:

- `◎` スキルを対応する `○` スキルとして表示・計算
- 金スキルを対応する下位の白スキルとして表示・計算
- 因子にできないスキルだけを表示と計算から除外
- 同じスキル系統が両方の段階にある場合は「超おすすめ」を優先

本育成モード:

- 金スキルを含めた確認を想定

この判定は `src/lib/utils.ts` に集約しています。
