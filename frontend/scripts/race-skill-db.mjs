// RaceSkillスクリプト共通ロジック(import/export両方から使う)
import { PrismaClient } from "@prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";

export const TIERS = {
  super: "super_recommended",
  super_recommended: "super_recommended",
  "超おすすめ": "super_recommended",
  "超おすすめスキル": "super_recommended",
  recommended: "recommended",
  normal: "recommended",
  "おすすめ": "recommended",
  "おすすめスキル": "recommended",
};

export const READY_STATUSES = new Set(["ready", "approved", "ok", "公開", "確認済み"]);

export function normalizeTier(value) {
  return TIERS[(value || "").trim()] ?? null;
}

export function normalizeStatus(value) {
  const status = (value || "").trim();
  if (!status) return "draft";
  return READY_STATUSES.has(status.toLowerCase()) || READY_STATUSES.has(status)
    ? "ready"
    : status;
}

export function getPrisma() {
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    console.error("DATABASE_URL が設定されていません。");
    console.error('例: $env:DATABASE_URL="postgresql://uma:PASSWORD@uma-pi:5432/uma_tool"');
    process.exit(1);
  }
  const adapter = new PrismaPg({ connectionString });
  return new PrismaClient({ adapter, log: ["error", "warn"] });
}

// 最小限のCSVパーサ(クォート対応、UTF-8 BOM除去)
export function parseCsv(text) {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const rows = [];
  let field = "";
  let row = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length) {
    row.push(field);
    if (row.length > 1 || row[0] !== "") rows.push(row);
  }
  if (!rows.length) return [];
  const header = rows[0].map((h) => h.trim());
  return rows.slice(1).map((cells) => {
    const record = {};
    header.forEach((key, index) => {
      record[key] = (cells[index] ?? "").trim();
    });
    return record;
  });
}
