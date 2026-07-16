// 抽出CSVをRaceSkillテーブルへ取り込む。
//
// 使い方:
//   node scripts/import-race-skills.mjs [--event 2026-07_CM] [--dry-run] <CSVファイル or フォルダ>...
//
// 例(リポジトリのfrontendディレクトリで):
//   node scripts/import-race-skills.mjs --event 2026-07_CM ../backend/data/guide_import/extracted
//
// 同じ (race, strategy, tier, skill) の行は上書きせずスキップする
// (Prisma Studioでの手修正を消さないため)。
import fs from "node:fs";
import path from "node:path";
import { getPrisma, normalizeTier, normalizeStatus, parseCsv } from "./race-skill-db.mjs";

function collectCsvFiles(target) {
  const stat = fs.statSync(target);
  if (stat.isFile()) return target.endsWith(".csv") ? [target] : [];
  return fs
    .readdirSync(target, { withFileTypes: true, recursive: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".csv"))
    .map((entry) => path.join(entry.parentPath ?? entry.path, entry.name));
}

async function main() {
  const args = process.argv.slice(2);
  let event = "";
  let dryRun = false;
  const targets = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--event") event = args[++i] ?? "";
    else if (args[i] === "--dry-run") dryRun = true;
    else targets.push(args[i]);
  }
  if (!targets.length) {
    console.error("CSVファイルまたはフォルダを指定してください。");
    process.exit(1);
  }

  const files = targets.flatMap(collectCsvFiles);
  if (!files.length) {
    console.error("CSVファイルが見つかりません。");
    process.exit(1);
  }

  const prisma = getPrisma();
  let inserted = 0;
  let skipped = 0;
  let invalid = 0;

  for (const file of files) {
    const records = parseCsv(fs.readFileSync(file, "utf-8"));
    for (const record of records) {
      const race = record.race ?? "";
      const strategy = record.strategy ?? "";
      const tier = normalizeTier(record.tier);
      const skill = record.skill ?? "";
      if (!race || !strategy || !tier || !skill) {
        invalid++;
        continue;
      }
      if (dryRun) {
        inserted++;
        continue;
      }
      try {
        await prisma.raceSkill.create({
          data: {
            event,
            race,
            strategy,
            tier,
            skill,
            status: normalizeStatus(record.status),
            sourceFile: record.source_file ?? "",
            memo: record.memo ?? "",
          },
        });
        inserted++;
      } catch (error) {
        const message = String(error?.message ?? "");
        if (error?.code === "P2002" || message.includes("Unique constraint")) {
          skipped++; // 既存行(ユニーク制約)はスキップ
        } else {
          throw error;
        }
      }
    }
    console.log(`${file}: 処理完了`);
  }

  console.log(
    `${dryRun ? "[dry-run] " : ""}追加 ${inserted} 件 / 既存スキップ ${skipped} 件 / 不正行 ${invalid} 件`
  );
  await prisma.$disconnect();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
