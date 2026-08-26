# new-umamusu-tool 作業ガイド

ウマ娘の因子周回向けサポカ編成ツール。詳細はREADME.mdを必ず読むこと。

## 全体像

- 公開サイト: https://new-umamusu-tool.vercel.app/ (完全静的、output: export。Cloudflare Pages移行準備中)
- 編成保存はlocalStorage(3スロット)。本番にサーバ処理・DBなし
- 公開データ: `frontend/src/data/race_data.json` など静的JSON。これが本番の正
- 編集用DB: ラズパイ(uma-pi)のPostgreSQLにRaceSkillテーブル。Prisma Studioで確認・修正し、`npm run skills:export` でJSONへ書き出す
- ラズパイ側の自動化: `/home/katao/uma-tool-automation`(公式ニュース監視、Gemini抽出、Discord通知、アップロードGUI http://uma-pi:8080)

## データ更新フロー

```
スクショ(tools/screenshot/のホットキーで撮影→ラズパイ転送)
  -> Gemini抽出CSV(ラズパイ、batch+skill_master自動補正)
  -> npm run skills:import(RaceSkillテーブルへ)
  -> Prisma Studioで確認・修正(status: draft -> ready、unknown_skill行を重点確認)
  -> npm run skills:export(race_data.jsonへ) -> コミット -> 自動デプロイ
```

GameToraのスキルデータ更新はラズパイのgametora_skills_watch.pyが15分おきに監視し、Discordへ通知する。

手順の詳細はREADME「Prismaによるスキル修正管理」を参照。

## 環境

- PC: Windows。リポジトリは C:\tmp\new-umamusu-tool
- ラズパイ: `ssh katao@uma-pi` で接続(Tailscale経由でも可)
- フロント開発: `cd frontend && npm run dev`

## 重要な注意

- **DATABASE_URLは必ずラズパイのPostgreSQL(uma-pi:5432/uma_tool)に向けること。Vercel本番の編成保存DBには触らない**
- `_pi/` はラズパイからのローカルコピーでAPIキー等を含む。コミット禁止(gitignore済み)
- 因子周回モードでは `◎` スキルと `non_factor_skills.json` 記載のスキルを除外する仕様
- スキルデータの手編集はrace_data.jsonに直接せず、DB経由(Prisma Studio)で行う

## 作業スタイル

- 破壊的な操作(DB初期化、ファイル削除、本番反映)は実行前に必ず確認を取る
- 大きな作業は1ステップずつ報告しながら進める
