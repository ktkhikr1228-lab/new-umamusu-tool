// RaceSkillテーブルから frontend/src/data/race_data.json を書き出す。
//
// 使い方:
//   node scripts/export-race-data.mjs [--include-draft] [--merge] [--output <path>] [--dry-run]
//
// 既定では status=ready の行のみを対象に、JSONを丸ごと作り直す(DBが正)。
// --merge を付けると既存JSONへ追記マージ(build_race_data.py の既定と同じ挙動)。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getPrisma } from "./race-skill-db.mjs";

const FRONTEND_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_OUTPUT = path.join(FRONTEND_ROOT, "src", "data", "race_data.json");

async function main() {
  const args = process.argv.slice(2);
  let includeDraft = false;
  let merge = false;
  let dryRun = false;
  let output = DEFAULT_OUTPUT;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--include-draft") includeDraft = true;
    else if (args[i] === "--merge") merge = true;
    else if (args[i] === "--dry-run") dryRun = true;
    else if (args[i] === "--output") output = path.resolve(args[++i] ?? DEFAULT_OUTPUT);
  }

  const prisma = getPrisma();
  const rows = await prisma.raceSkill.findMany({
    where: includeDraft ? { status: { not: "rejected" } } : { status: "ready" },
    orderBy: { id: "asc" },
  });
  await prisma.$disconnect();

  let data = {};
  if (merge && fs.existsSync(output)) {
    data = JSON.parse(fs.readFileSync(output, "utf-8"));
  }

  let count = 0;
  for (const row of rows) {
    const tier = row.tier === "super_recommended" ? "super_recommended" : "recommended";
    data[row.race] ??= {};
    data[row.race][row.strategy] ??= { super_recommended: [], recommended: [] };
    const target = (data[row.race][row.strategy][tier] ??= []);
    if (!target.includes(row.skill)) target.push(row.skill);
    count++;
  }

  if (dryRun) {
    console.log(JSON.stringify({ output, included_rows: count, race_count: Object.keys(data).length }, null, 2));
    return;
  }

  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(data, null, 2) + "\n", "utf-8");
  console.log(`${count} 行を ${output} に書き出しました。`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
