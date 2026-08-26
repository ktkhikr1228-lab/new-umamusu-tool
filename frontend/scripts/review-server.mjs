// レビューページの「DBに適用」ボタンを受けるローカルサーバ。
//
// 使い方(frontendディレクトリで、DATABASE_URL設定済みの状態):
//   node scripts/review-server.mjs
//
// レビューページ(review_*.html)を開いたまま起動しておくと、
// ページ上の修正をボタン一発でDBへ適用できる。止めるのは Ctrl+C。
//
// 安全のため:
// - localhostからのアクセスのみ
// - 実行できるのは RaceSkill への UPDATE 文のみ
import http from "node:http";
import { Client } from "pg";

const PORT = 5959;

if (!process.env.DATABASE_URL) {
  console.error("DATABASE_URL が設定されていません。");
  process.exit(1);
}

const server = http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204).end();
    return;
  }
  if (req.method !== "POST" || req.url !== "/apply") {
    res.writeHead(404).end("not found");
    return;
  }

  let body = "";
  for await (const chunk of req) body += chunk;

  let changes;
  try {
    changes = JSON.parse(body).changes;
    if (!Array.isArray(changes)) throw new Error("changes must be an array");
  } catch (error) {
    res.writeHead(400, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: `bad request: ${error.message}` }));
    return;
  }

  const client = new Client({ connectionString: process.env.DATABASE_URL });
  const results = [];
  try {
    await client.connect();
    await client.query("BEGIN");
    for (const change of changes) {
      const { race, strategy, tier, skill, newName, reject } = change;
      if (!race || !strategy || !tier || !skill) {
        throw new Error("race/strategy/tier/skill は必須です");
      }
      const whereArgs = [race, strategy, tier, skill];

      if (reject) {
        const r = await client.query(
          `update "RaceSkill" set status = 'rejected', memo = 'manual_reject'
           where race = $1 and strategy = $2 and tier = $3 and skill = $4`,
          whereArgs
        );
        results.push({ skill, action: "除外", rows: r.rowCount });
        continue;
      }

      if (!newName || newName === skill) continue;

      // 修正先がDB上に既に存在するか確認して、改名か除外かを決める
      const dup = await client.query(
        `select 1 from "RaceSkill"
         where race = $1 and strategy = $2 and tier = $3 and skill = $4`,
        [race, strategy, tier, newName]
      );
      if (dup.rowCount > 0) {
        const r = await client.query(
          `update "RaceSkill" set status = 'rejected', memo = $5
           where race = $1 and strategy = $2 and tier = $3 and skill = $4`,
          [...whereArgs, `manual_reject:${newName}と重複`]
        );
        results.push({ skill, action: `除外(${newName}が既存)`, rows: r.rowCount });
      } else {
        const r = await client.query(
          `update "RaceSkill" set skill = $5, memo = $6
           where race = $1 and strategy = $2 and tier = $3 and skill = $4`,
          [...whereArgs, newName, `manual_fix:${skill}->${newName}`]
        );
        results.push({ skill, action: `改名->${newName}`, rows: r.rowCount });
      }
    }
    await client.query("COMMIT");
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, results }));
    console.log(`適用: ${results.length}件`);
    for (const r of results) console.log(`  ${r.skill}: ${r.action} (${r.rows}行)`);
  } catch (error) {
    try {
      await client.query("ROLLBACK");
    } catch {}
    res.writeHead(500, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: error.message }));
    console.error("失敗(全件ロールバック):", error.message);
  } finally {
    await client.end();
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`review-server: http://localhost:${PORT} で待機中 (Ctrl+Cで終了)`);
});
