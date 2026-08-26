"""抽出CSVとスクショを見比べるレビューページ(HTML)を生成する。

使い方(PC、リポジトリルートで):

  python backend/tools/build_review_page.py ^
    --csv "backend/data/guide_import/extracted_pi_preview/2026-07_CM/中山_芝_3600m_1_nige.csv" ^
    --images-dir "%USERPROFILE%/uma-shots/2026-07_CM/1_nige" ^
    --output review_nige.html

生成されたHTMLをブラウザで開くと、スクショごとに
「画像 | 抽出された行」が横並びで表示される。
- 赤帯: unknown_skill(要確認) - 画像と見比べて Prisma Studio で修正/reject
- 黄帯: auto_fix(自動修正済み) - 修正が正しいか目視
"""
from __future__ import annotations

import argparse
import csv
import html
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("review.html"))
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"CSVが見つかりません: {args.csv}", file=sys.stderr)
        return 1

    with args.csv.open("r", encoding="utf-8-sig", newline="") as file:
        rows = [dict(row) for row in csv.DictReader(file)]

    by_source: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_source.setdefault(row.get("source_file", ""), []).append(row)

    images_dir = args.images_dir.resolve()

    def row_class(memo: str) -> str:
        if "unknown_skill" in memo:
            return "unknown"
        if "auto_fix" in memo:
            return "fixed"
        return ""

    sections: list[str] = []
    unknown_total = 0
    fixed_total = 0
    for source_file in sorted(by_source):
        source_rows = by_source[source_file]
        image_path = images_dir / source_file
        img_tag = (
            f'<img src="{html.escape(image_path.as_uri())}" alt="{html.escape(source_file)}">'
            if image_path.exists()
            else f'<div class="noimg">画像が見つかりません:<br>{html.escape(str(image_path))}</div>'
        )

        rows_html = []
        for row in source_rows:
            memo = row.get("memo", "")
            cls = row_class(memo)
            if cls == "unknown":
                unknown_total += 1
            elif cls == "fixed":
                fixed_total += 1
            tier_label = "超" if row.get("tier") == "super_recommended" else "推"
            skill = row.get("skill", "")
            attrs = (
                f'data-race="{html.escape(row.get("race", ""), quote=True)}" '
                f'data-strategy="{html.escape(row.get("strategy", ""), quote=True)}" '
                f'data-tier="{html.escape(row.get("tier", ""), quote=True)}" '
                f'data-skill="{html.escape(skill, quote=True)}" '
                f'data-source-file="{html.escape(row.get("source_file", ""), quote=True)}"'
            )
            rows_html.append(
                f'<tr class="{cls}" {attrs}><td class="tier">{tier_label}</td>'
                f'<td><input class="name" value="{html.escape(skill, quote=True)}"></td>'
                f'<td class="rej"><label><input type="checkbox" class="reject">除外</label></td>'
                f"<td class='memo'>{html.escape(memo)}</td></tr>"
            )

        sections.append(
            f"""
<section>
  <h2>{html.escape(source_file)} <small>({len(source_rows)}件)</small></h2>
  <div class="pair">
    <div class="shot">{img_tag}</div>
    <table>
      <thead><tr><th></th><th>スキル(直接編集できます)</th><th></th><th>memo</th></tr></thead>
      <tbody>{''.join(rows_html)}</tbody>
    </table>
  </div>
</section>"""
        )

    title = f"抽出レビュー: {args.csv.stem}"
    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ font-family: "Segoe UI", "Yu Gothic UI", sans-serif; margin: 16px; background: #f5f5f7; }}
  h1 {{ font-size: 18px; }}
  .summary {{ margin-bottom: 16px; color: #444; }}
  .summary .u {{ color: #b91c1c; font-weight: bold; }}
  .summary .f {{ color: #92400e; font-weight: bold; }}
  section {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; }}
  h2 {{ font-size: 14px; margin: 0 0 10px; }}
  .pair {{ display: flex; gap: 16px; align-items: flex-start; }}
  .shot {{ flex: 0 0 380px; position: sticky; top: 8px; }}
  .shot img {{ width: 100%; border: 1px solid #ccc; border-radius: 6px; }}
  .noimg {{ padding: 30px 10px; background: #eee; border-radius: 6px; font-size: 12px; color: #666; }}
  table {{ border-collapse: collapse; font-size: 13px; flex: 1; }}
  th, td {{ border-bottom: 1px solid #eee; padding: 4px 10px; text-align: left; }}
  td.tier {{ font-weight: bold; color: #666; }}
  td.memo {{ font-size: 11px; color: #888; }}
  tr.unknown {{ background: #fee2e2; }}
  tr.unknown td.memo {{ color: #b91c1c; font-weight: bold; }}
  tr.fixed {{ background: #fef3c7; }}
  tr.fixed td.memo {{ color: #92400e; }}
  input.name {{ width: 220px; font-size: 13px; padding: 2px 6px; border: 1px solid #ccc; border-radius: 4px; background: transparent; }}
  tr.changed input.name {{ border-color: #2563eb; background: #dbeafe; }}
  td.rej {{ font-size: 11px; color: #666; white-space: nowrap; }}
  #sqlbar {{ position: fixed; bottom: 0; left: 0; right: 0; background: #111827; color: #eee; padding: 10px 16px; box-shadow: 0 -2px 8px rgba(0,0,0,.3); }}
  #sqlbar button {{ font-size: 13px; padding: 6px 14px; border-radius: 6px; border: none; background: #16a34a; color: #fff; cursor: pointer; margin-right: 10px; }}
  #sqlbar button.sub {{ background: #2563eb; }}
  tr.applied input.name {{ border-color: #16a34a; background: #dcfce7; }}
  #sqlbar textarea {{ width: 100%; height: 90px; margin-top: 8px; font-family: Consolas, monospace; font-size: 12px; background: #1f2937; color: #d1fae5; border: 1px solid #374151; border-radius: 6px; display: none; }}
  body {{ padding-bottom: 160px; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<div class="summary">
  全{len(rows)}行 / <span class="u">要確認 {unknown_total}件(赤)</span> /
  <span class="f">自動修正 {fixed_total}件(黄)</span><br>
  赤帯は画像と見比べて修正してください。CSV保存で修正内容を次のJSON反映に渡せます。
</div>
{''.join(sections)}
<div id="sqlbar">
  <button onclick="downloadCsv()" class="sub">修正済みCSVを保存</button>
  <button onclick="applyToDb()" id="applybtn">DBに適用</button>
  <button onclick="generateSql()" class="sub">SQLを表示</button>
  <span id="sqlinfo">名前を修正・除外してから「修正済みCSVを保存」を押してください。DBに適用は旧機能です。</span>
  <textarea id="sqlout" readonly onclick="this.select()"></textarea>
</div>
<script>
function esc(v) {{ return v.replaceAll("'", "''"); }}
function csvCell(v) {{
  return '"' + String(v ?? '').replaceAll('"', '""') + '"';
}}

function downloadCsv() {{
  const header = ['race', 'strategy', 'tier', 'skill', 'source_file', 'status', 'memo'];
  const lines = [header.map(csvCell).join(',')];
  document.querySelectorAll('tbody tr').forEach((tr) => {{
    const d = tr.dataset;
    const input = tr.querySelector('input.name');
    const rejected = tr.querySelector('input.reject').checked;
    const skill = input.value.trim();
    const changed = skill !== d.skill;
    const needsReview = tr.classList.contains('unknown') || tr.classList.contains('fixed');
    const status = rejected ? 'rejected' : (needsReview && !changed ? 'draft' : 'ready');
    let memo = rejected ? 'manual_reject' : '';
    if (changed) memo = `manual_fix:${{d.skill}}->${{skill}}`;
    lines.push([
      d.race, d.strategy, d.tier, skill, d.sourceFile, status, memo,
    ].map(csvCell).join(','));
  }});

  const blob = new Blob(["\\uFEFF" + lines.join('\\r\\n')], {{type: 'text/csv;charset=utf-8'}});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = '{html.escape(args.csv.stem)}_reviewed.csv';
  link.click();
  URL.revokeObjectURL(url);
  document.getElementById('sqlinfo').textContent = '修正済みCSVを保存しました。Codexへ渡してJSONへ反映できます。';
}}

document.addEventListener("input", (e) => {{
  const tr = e.target.closest("tr");
  if (!tr) return;
  const changed = tr.querySelector("input.name").value.trim() !== tr.dataset.skill
    || tr.querySelector("input.reject").checked;
  tr.classList.toggle("changed", changed);
}});
function collectStatements() {{
  // ページ内の全行から「race|strategy|tier|skill」の既存キー集合を作る
  const existing = new Set();
  document.querySelectorAll("tbody tr").forEach((tr) => {{
    const d = tr.dataset;
    existing.add(`${{d.race}}|${{d.strategy}}|${{d.tier}}|${{d.skill}}`);
  }});

  const lines = [];
  document.querySelectorAll("tbody tr").forEach((tr) => {{
    const d = tr.dataset;
    const where = `race = '${{esc(d.race)}}' and strategy = '${{esc(d.strategy)}}' and tier = '${{esc(d.tier)}}' and skill = '${{esc(d.skill)}}'`;
    const newName = tr.querySelector("input.name").value.trim();
    if (tr.querySelector("input.reject").checked) {{
      lines.push(`update RaceSkill set status = 'rejected', memo = 'manual_reject' where ${{where}};`);
    }} else if (newName && newName !== d.skill) {{
      // 修正先が同じrace/strategy/tierに既に存在するなら、改名ではなく除外にする
      if (existing.has(`${{d.race}}|${{d.strategy}}|${{d.tier}}|${{newName}}`)) {{
        lines.push(`update RaceSkill set status = 'rejected', memo = 'manual_reject:${{esc(newName)}}と重複' where ${{where}};`);
      }} else {{
        lines.push(`update RaceSkill set skill = '${{esc(newName)}}', memo = 'manual_fix:${{esc(d.skill)}}->${{esc(newName)}}' where ${{where}};`);
      }}
    }}
  }});
  return lines;
}}

function generateSql() {{
  const lines = collectStatements();
  const out = document.getElementById("sqlout");
  const info = document.getElementById("sqlinfo");
  if (!lines.length) {{
    info.textContent = "変更がありません。名前を書き換えるか「除外」にチェックしてください。";
    out.style.display = "none";
    return;
  }}
  out.value = lines.join("\\n");
  out.style.display = "block";
  info.textContent = `${{lines.length}}件の修正SQL。コピーして fixes.sql に保存し、frontend で: node scripts/db-query.mjs --file fixes.sql`;
  out.focus();
  out.select();
}}

function collectChanges() {{
  const changes = [];
  document.querySelectorAll("tbody tr").forEach((tr) => {{
    const d = tr.dataset;
    const newName = tr.querySelector("input.name").value.trim();
    const reject = tr.querySelector("input.reject").checked;
    if (reject || (newName && newName !== d.skill)) {{
      changes.push({{
        race: d.race,
        strategy: d.strategy,
        tier: d.tier,
        skill: d.skill,
        newName: newName,
        reject: reject,
      }});
    }}
  }});
  return changes;
}}

async function applyToDb() {{
  const info = document.getElementById("sqlinfo");
  const changes = collectChanges();
  if (!changes.length) {{
    info.textContent = "変更がありません。名前を書き換えるか「除外」にチェックしてください。";
    return;
  }}
  const btn = document.getElementById("applybtn");
  btn.disabled = true;
  info.textContent = `${{changes.length}}件を適用中...`;
  try {{
    const res = await fetch("http://localhost:5959/apply", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ changes: changes }}),
    }});
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || res.statusText);
    const summary = data.results.map((r) => `${{r.skill}}:${{r.action}}`).join(" / ");
    info.textContent = `適用完了: ${{summary}}`;
    document.querySelectorAll("tr.changed").forEach((tr) => {{
      tr.classList.remove("changed");
      tr.classList.add("applied");
    }});
  }} catch (error) {{
    info.textContent = `適用失敗: ${{error.message}} — review-serverが起動しているか確認してください (node scripts/review-server.mjs)`;
  }} finally {{
    btn.disabled = false;
  }}
}}
</script>
</body>
</html>"""

    args.output.write_text(page, encoding="utf-8")
    print(f"生成: {args.output} (画像 {len(by_source)}枚 / {len(rows)}行 / 要確認{unknown_total} / 自動修正{fixed_total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
