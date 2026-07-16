// 編集用DBへ任意のSQLを実行する小道具。
//
// 使い方(PowerShellでは全体をシングルクォートで囲む):
//   node scripts/db-query.mjs 'select count(*) from "RaceSkill"'
//   node scripts/db-query.mjs 'delete from "RaceSkill" where id = 123'
//
// DATABASE_URL が必要。SELECT系は表で表示、更新系は影響行数を表示する。
import { Client } from "pg";

import fs from "node:fs";

let sql = process.argv[2];
// --file fixes.sql でファイルから読む(クォート地獄を回避)
if (sql === "--file" && process.argv[3]) {
  sql = fs.readFileSync(process.argv[3], "utf-8");
}
// PowerShellは引数中の二重引用符を落とすことがあるため、
// 裸のテーブル名を自動でクォートする(RaceSkill / Deck)
if (sql) {
  sql = sql.replace(/(?<!")\b(RaceSkill|Deck)\b(?!")/g, '"$1"');
}
if (!sql) {
  console.error("SQLを引数で渡してください。");
  process.exit(1);
}
if (!process.env.DATABASE_URL) {
  console.error("DATABASE_URL が設定されていません。");
  process.exit(1);
}

const client = new Client({ connectionString: process.env.DATABASE_URL });
try {
  await client.connect();
  const result = await client.query(sql);
  const results = Array.isArray(result) ? result : [result];
  for (const r of results) {
    if (r.rows?.length) {
      console.table(r.rows);
    }
    console.log(`command: ${r.command} / rows: ${r.rowCount ?? 0}`);
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  await client.end();
}
