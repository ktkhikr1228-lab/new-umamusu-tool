# GameTora import files

GameTora由来のサポートカードJSONを `frontend/src/data/cards.json` に取り込むための作業場所です。

## 更新対象

- `support-cards`
- `skills`
- `training_events/ssr`
- `training_events/sr`

ヒントスキルとイベントスキルは、フロントで扱いやすいように各カードの `skills` 配列へまとめます。

## 自動更新

`backend` ディレクトリから実行します。

```powershell
python tools\import_gametora_cards.py --download-latest
```

このコマンドはGameToraのmanifestを見て、最新のハッシュ付きJSONを取得します。

環境によって `python` が見つからない場合は、Codexの同梱PythonなどフルパスのPythonに置き換えてください。

## 手動更新

コマンドラインからGameToraの取得がブロックされる場合は、ブラウザでJSONを保存してこのフォルダへ置きます。

ファイル名の例:

```text
support-cards.HASH.json
skills.HASH.json
ssr.HASH.json
sr.HASH.json
```

実行例:

```powershell
python tools\import_gametora_cards.py `
  --support-cards data\import\support-cards.HASH.json `
  --skills data\import\skills.HASH.json `
  --ssr-events data\import\ssr.HASH.json `
  --sr-events data\import\sr.HASH.json
```

SSR/SRイベントがまだ無い場合は、まず `support-cards` と `skills` だけでも取り込めます。

```powershell
python tools\import_gametora_cards.py `
  --support-cards data\import\support-cards.HASH.json `
  --skills data\import\skills.HASH.json
```

## 更新後に確認すること

リポジトリ直下に戻ってから確認します。

```powershell
cd ..\frontend
npm run lint
npm run build
```

確認ポイント:

- `frontend/src/data/cards.json` のカード数が増えているか
- 主要カードのタイプが正しいか
- 新しいカードのスキルが表示されるか
- Vercelのプレビューで表示が崩れていないか

## メモ

`rare_skills` はフロント互換のため残していますが、現在の表示・計算では主に `skills` を参照します。
