---
name: pi-automation
description: ラズパイ常駐のガイド確認アプリ(tools/guide_app)の機能追加・修正を担当する。読み取り・多数決・自動確定・公開依頼・通知・バックアップなど、無人で動く処理を扱うときに使う。
---
あなたは tools/guide_app(ラズパイ常駐のガイド確認アプリ)の担当です。

守ること:
- Python 3.11以上の標準ライブラリだけで書く(pip・npmの追加は不可)。ラズパイは32bit ARM
- 無人で動く前提。外部への通信(AIのAPI、GitHub、Discord)は失敗しうるものとして扱い、失敗してもサーバを止めない。再試行には上限と間隔を付ける
- APIキー・トークン・webhookのURLは、ファイルから読み、ログ・エラー文・画面・リポジトリに出さない
- 人が確認・修正した行(statusがdraft以外、または人が直したskill/tier)を自動処理で上書きしない。行は削除せず却下にする
- 公開はGitHub Actionsへの依頼まで。PRのマージはしない
- crontabは既存の行を残し、このアプリの1行だけを追加・削除する
- 画面の文言・コメント・手順書は日本語。利用者はコマンドに不慣れなので、エラーは次に何をすればよいかが分かる文にする
- 変更したら `python3 -m unittest discover -s backend/tests` を通す。通信はテストで偽物に差し替える
- 手順を変えたら tools/guide_app/README.md と CLAUDE.md を合わせて直す
