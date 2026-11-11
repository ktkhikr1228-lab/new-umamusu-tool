# new-umamusu-tool 作業ガイド

ウマ娘の因子周回向けサポカ編成ツール。詳細はREADME.mdを必ず読むこと。

## 全体像

- 公開サイト: https://new-umamusu-tool.vercel.app/ (完全静的、output: export。Cloudflare Pages移行準備中)
- 編成保存はlocalStorage(3スロット)。本番にサーバ処理・DBなし
- 公開データ: `frontend/src/data/race_data.json` など静的JSON。これが本番の正
- おすすめスキルの確認・公開: ラズパイ常駐の **ガイド確認アプリ**(`tools/guide_app/`、http://uma-pi:8090)。Python標準ライブラリ+SQLiteだけで動く。手順は `tools/guide_app/README.md`
- ラズパイ側の自動化: `/home/katao/uma-tool-automation`(公式ニュース監視、Gemini抽出、Discord通知、アップロードGUI http://uma-pi:8080)

## おすすめスキルの更新フロー

```
スクショ(tools/screenshot/ のF8で撮影 → ラズパイへ転送)
  -> Gemini抽出(アップロードGUI 8080。CSVは extracted/<イベント>/ に出力)
  -> ガイド確認アプリが5分おきに自動取り込み(SQLite)
  -> 確認画面でスクショと照合(マスタにない名前・◎・両区分・サイトと区分違いだけ要確認)
  -> 公開画面で「公開を依頼する」(OKかつサイトにない/区分が違う行だけ)
  -> GitHub Actions(publish-reviewed-race-data.yml)が検証・ビルドしてPR作成
  -> 人がPRをマージ -> 自動デプロイ
```

- サイトの内容(mainの race_data.json)と比べるので、公開済みのスキルは見直し不要
- 公開は「前回分に追加」。サイトにある他のスキルは消さない。区分の違いは新しいイベントで上書き
- サポカデータ(GameTora)は別系統: `update-gametora-data.yml` が毎日取得してPRを作る。ラズパイの gametora_skills_watch.py が更新を監視しDiscordへ通知

## 環境

- PC: Windows。作業場所は `C:\Users\katao\uma-tool-workspace\current\new-umamusu-tool`
- ラズパイ: `ssh katao@uma-pi` で接続(Tailscale経由でも可)。リポジトリは `~/new-umamusu-tool`
- ガイド確認アプリの操作: `bash tools/guide_app/guide_app.sh status|update|restart|log`(cron @reboot で自動起動)
- フロント開発: `cd frontend && npm run dev`

## 重要な注意

- `_pi/` はラズパイからのローカルコピーでAPIキー等を含む。コミット禁止(gitignore済み)
- ラズパイの `~/.config/uma-tool/github_token` は公開依頼(Actions起動)用。リポジトリやログに出さない
- 因子周回モードでは `◎` スキルと `non_factor_skills.json` 記載のスキルを除外する仕様
- スキルデータの手編集はrace_data.jsonに直接せず、ガイド確認アプリ経由(公開依頼→PR)で行う
- ガイド確認アプリのcron登録は既存の行を残して1行だけ追加・削除する。crontabを丸ごと書き換えない
- ラズパイのPostgreSQL(uma_tool の RaceSkill テーブル)は旧手順の名残。Prismaはリポジトリから外した。新しい作業には使わない

## 作業スタイル

- 破壊的な操作(DB初期化、ファイル削除、本番反映)は実行前に必ず確認を取る
- 大きな作業は1ステップずつ報告しながら進める
