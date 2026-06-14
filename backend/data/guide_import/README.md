# Trainer guide import

トレーナーガイドのスクショから、レース条件ごとのスキルCSVを作るための作業メモです。

画像ファイルはGitHubに入れず、ローカルフォルダに置く運用を想定しています。

## 推奨フォルダ

```text
C:\Users\katao\uma-guide-data\
  screenshots\
    26-06_CM\
      1_nige\
        01.png
        02.png
      2_senkou\
      3_sashi\
      4_oikomi\
```

Google Drive for desktopを使う場合も、Pythonからは同期済みのローカルフォルダとして読みます。

## 1. スクショからCSVを作る

リポジトリ直下から実行します。

```powershell
python backend\tools\extract_trainer_guide.py `
  --input-dir C:\Users\katao\uma-guide-data\screenshots\26-06_CM\1_nige `
  --race "東京 芝 2400m" `
  --strategy "逃げ" `
  --output backend\data\guide_import\extracted\26-06_CM_nige.csv
```

`python` が見つからない場合は、Codex同梱Pythonなどのフルパスに置き換えます。

```powershell
C:\Users\katao\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe backend\tools\extract_trainer_guide.py `
  --input-dir C:\Users\katao\uma-guide-data\screenshots\26-06_CM\1_nige `
  --race "東京 芝 2400m" `
  --strategy "逃げ" `
  --output backend\data\guide_import\extracted\26-06_CM_nige.csv
```

事前に `GEMINI_API_KEY` を設定します。

```powershell
$env:GEMINI_API_KEY="YOUR_API_KEY"
```

使うモデルを変える場合:

```powershell
$env:GEMINI_MODEL="gemini-2.5-flash"
```

画像一覧だけ確認したい場合:

```powershell
python backend\tools\extract_trainer_guide.py `
  --input-dir C:\Users\katao\uma-guide-data\screenshots\26-06_CM\1_nige `
  --race "東京 芝 2400m" `
  --strategy "逃げ" `
  --dry-run
```

## 2. 抽出CSVを機械チェックする

抽出後に、既知スキル名・非因子スキル・よくあるOCRミスをまとめて確認します。

```powershell
python backend\tools\check_extracted_skills.py `
  --input-glob "backend\data\guide_import\extracted\*.csv"
```

代表的なOCRミスを反映した確認用CSVを作る場合:

```powershell
python backend\tools\check_extracted_skills.py `
  --input-glob "backend\data\guide_import\extracted\*.csv" `
  --write-fixed backend\data\guide_import\checked\race_skills_checked.csv
```

この時点では `status` は `draft` のままです。目視で確認して、サイトに反映してよい行だけ `ready` にします。

## 3. CSVを確認する

Gemini抽出直後のCSVは `status` が `draft` です。

人間が確認したら、`checked/race_skills_checked.csv` に貼り付けて `status` を `ready` にします。

CSV列:

```csv
race,strategy,tier,skill,source_file,status,memo
```

`tier` は以下のどちらかです。

```text
super_recommended
recommended
```

## 4. race_data.jsonを生成する

```powershell
python backend\tools\build_race_data.py `
  --input backend\data\guide_import\checked\race_skills_checked.csv `
  --output frontend\src\data\race_data.json
```

書き込み前に確認したい場合:

```powershell
python backend\tools\build_race_data.py --dry-run
```

## 運用メモ

- スクショ原本はローカルだけで管理
- `extracted` はGeminiの生出力に近いCSV
- `checked` は人間が確認したCSV
- サイトが読む最終データは `frontend/src/data/race_data.json`
- 因子周回で `◎` や金スキルを非表示にする処理はフロント側で行う
