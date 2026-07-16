# Raspberry Pi CSV sync

ラズパイで抽出したトレーナーガイドCSVを、PC側のリポジトリへ取り込んで `race_data.json` まで更新する手順です。

## 前提

- Windows側で `ssh uma-pi` が通る
- ラズパイ側のCSVは `/home/katao/uma-guide-data/extracted` にある
- PC側のリポジトリは `C:\tmp\new-umamusu-tool`

## いつもの更新コマンド

```powershell
cd C:\tmp\new-umamusu-tool
python backend\tools\sync_pi_guide_data.py --run-next-build
```

このコマンドで行うこと:

1. `scp` でラズパイの抽出CSVを `backend\data\guide_import\extracted` にコピー
2. `check_extracted_skills.py` でOCRミス候補を補正
3. `backend\data\guide_import\checked\race_skills_checked.csv` を更新
4. `frontend\src\data\race_data.json` を更新
5. `npm run build` で本番ビルド確認

## コピーせずに手元のCSVだけで再生成する

```powershell
python backend\tools\sync_pi_guide_data.py --skip-copy --run-next-build
```

## ready の行だけ反映する

通常は抽出直後の `draft` 行も含めて反映します。手動確認済みの行だけ使う場合は:

```powershell
python backend\tools\sync_pi_guide_data.py --ready-only --run-next-build
```

## GitHubへ反映する流れ

```powershell
git status
git switch -c codex/update-guide-data
git add backend\data\guide_import\checked\race_skills_checked.csv frontend\src\data\race_data.json
git commit -m "Update guide skill data"
git push -u origin codex/update-guide-data
```

GitHubでPRを作り、確認してマージするとVercel本番へ反映されます。
