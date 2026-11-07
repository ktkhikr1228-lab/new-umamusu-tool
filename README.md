# ウマ娘 因子周回サポカ編成ツール

『ウマ娘 プリティーダービー』の因子周回向けに、コース・脚質ごとのおすすめスキルを確認しながら、サポートカード編成を組むための非公式ツールです。

**[公開サイトを開く](https://new-umamusu-tool.vercel.app/)**

## 使い方

1. コースと脚質（逃げ・先行・差し・追込）を選びます。
2. 「因子周回」または「本育成」モードを選び、「超おすすめ」「おすすめ」のスキルを確認します。
3. カード名・キャラ名・スキル名で検索したり、カードタイプで絞り込んだりして、最大6枚の編成を組みます。候補の並び順は、編成に足りない目標スキルをもとに変わります。

編成は最大3枠までブラウザに自動保存されます。保存内容は同じブラウザ・同じ公開URLで利用でき、別端末とは同期しません。

### モードの違い

| モード | スキルの扱い |
| --- | --- |
| 因子周回 | 継承向けのスキルを使います。上位スキルは対応表に従って下位スキルへ読み替え、`◎` は `○` として扱います。継承対象外に指定されたスキルは除外します。 |
| 本育成 | 金スキルなども含めて確認できます。不足している目標スキルに対応する金スキルは、候補の評価で加点されます。 |

## ローカルで起動する

Node.js 22（CIと同じメジャーバージョン）とnpmを用意し、リポジトリのルートから実行します。

```sh
cd frontend
npm ci
npm run dev
```

ブラウザで [http://localhost:3000](http://localhost:3000) を開きます。公開画面の開発・閲覧に、PostgreSQLやGeminiの認証情報は不要です。

`npm run build` で `frontend/out/` に静的サイトを生成できます。公開先はVercelです。画面は同梱のJSONを読み込み、編成はブラウザに保存するため、編集用DBへ接続しません。

## データの更新と公開

### サポートカード：GameToraから取得

[データ更新ワークフロー](.github/workflows/update-gametora-data.yml) が、GameToraのカード・スキル・育成イベント情報から公開用データを生成します。実行予定は毎日 **12:15・15:00・18:00・21:00（日本時間）** です。手動実行もできます。

- カードデータや調査結果に差分があれば、`data/gametora-update` のPRを作成または更新します。カードデータに差分がある場合は静的ビルドも実行します。
- GameTora側でスキル一覧が空のカードは再調査します。検索で見つけた候補はレポートに記録し、人が確認した補完データとは分けて扱います。
- 補完データは確認済みのカードに限定し、元データにスキルが登録されれば元データを優先します。

詳細: [GameToraデータの取り込み](backend/data/import/README.md) ／ [未収録スキルの調査と補完](backend/tools/README_missing_skill_research.md)

### おすすめスキル：ゲーム内のトレーナーガイドから確認

1. Windowsの撮影ツールで脚質・区分を設定し、**F8** で撮影します。設定に応じて画像をRaspberry Piへ転送します。
2. Geminiでスキル名を抽出し、元画像と照合して誤読・区分・重複を確認します。抽出直後のデータは未確認です。
3. 確認済みCSVから公開依頼を作成します。GitHub Actionsがデータを再検証してPRを作成し、人が差分を確認してマージすると、Vercelのデプロイで反映されます。

詳細: [撮影・転送](tools/screenshot/README.md) ／ [抽出データの管理](backend/data/guide_import/README.md) ／ [確認済みデータの公開手順](docs/reviewed-race-publication.md)

Raspberry PiとPostgreSQLは撮影データの受け取り・抽出・編集などの運用に使います。DBへの取り込みや修正だけでは、公開サイトは更新されません。公開版のおすすめスキルは、イベント月別ではなく**コース・脚質別**の `race_data.json` にまとまっています。

## リポジトリ構成

| パス | 内容 |
| --- | --- |
| [`frontend/app/`](frontend/app/)・[`frontend/src/`](frontend/src/) | Next.js・React・TypeScript・Tailwind CSSによる公開画面と編成ロジック |
| [`frontend/src/data/`](frontend/src/data/) | 公開画面が参照するサポカ・レース・スキルのJSON |
| [`frontend/scripts/`](frontend/scripts/)・[`frontend/prisma/`](frontend/prisma/) | 運用者向けの編集DB操作 |
| [`backend/tools/`](backend/tools/)・[`backend/tests/`](backend/tests/) | データ取得・抽出・公開用スクリプトとテスト |
| [`tools/screenshot/`](tools/screenshot/) | Windowsでの撮影・転送ツール |
| [`.github/workflows/`](.github/workflows/) | データ更新・検証・公開PRの自動化 |

お問い合わせは公開サイト内のフォームからお願いします。

## Raspberry Piの運用画面

同じTailscaleネットワークに接続したPC・スマホから `http://uma-pi:8080/` にアクセスします。名前解決できない場合は `http://100.87.114.18:8080/` を使います。管理画面は一般公開しません。

- 抽出前に対象画像・スキップ件数・APIリクエスト数の見積もりを確認し、確認画面から抽出を開始します。撮影・転送だけではGeminiを呼び出しません。
- 同じ画像の再抽出を抑制し、`/operations` で処理状態を確認できます。現在の抽出モデルは `gemini-3.5-flash-lite` です。
- スマホ向けスキル修正画面、管理画面の公開ボタン、撮影設定の自動同期は未接続です。
- Piの監視時刻は日本時間12:15・12:45・14:15・15:00です。GitHub Actionsの時刻は上記ワークフロー設定と異なります。時刻変更は[PR #65](https://github.com/ktkhikr1228-lab/new-umamusu-tool/pull/65)で別途確認します。

Windowsの現在の作業場所は `C:\Users\katao\uma-tool-workspace\current\new-umamusu-tool` です。撮影イベント名は `tools/screenshot/current_event.txt` に設定します。Ctrl+Alt+1〜4で脚質、Ctrl+Alt+5・6で超おすすめ・おすすめを選び、ゲーム内のタブも手動で合わせてください。

画像はGitHubへコミットせず、PCの `%USERPROFILE%\uma-shots` とPiの `/home/katao/uma-guide-data/screenshots` で管理します。抽出CSVは `/home/katao/uma-guide-data/extracted`、運用スクリプトは `/home/katao/uma-tool-automation` に保存しています。

2026年11月LOH（京都・芝3000m）は画像収集中です。確認済みデータの公開PRは自動マージしません。同じコースの別イベントは既存データに統合されるため、季節スキルの全面入れ替えには別途レビューが必要です。
