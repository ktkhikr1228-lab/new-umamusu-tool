"""Research only cards reported without skills. Never modifies card/alias data."""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from import_gametora_cards import as_records, make_skill_map, read_json, write_json

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = {
    "gamewith.jp": "/uma-musume/article/show/",
    "game8.jp": "/umamusume/",
    "kamigame.jp": "/umamusume/",
}
SKILL_HEADINGS = {"育成イベント", "所持スキル", "育成イベントで取れるスキル",
                  "育成イベントで習得できるスキル", "ヒントで入手可能なスキル"}


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def source_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in SOURCE_PATHS
            and parsed.netloc == parsed.hostname
            and parsed.path.startswith(SOURCE_PATHS[parsed.hostname]))


class SearchLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            url = dict(attrs).get("href", "")
            if source_url(url) and url not in self.links:
                self.links.append(url)


class SkillPage(HTMLParser):
    """Collect visible text and heading-delimited blocks, excluding scripts."""
    def __init__(self):
        super().__init__()
        self.title: list[str] = []
        self.text: list[str] = []
        self.blocks: list[dict[str, Any]] = []
        self.heading_level = 0
        self.heading_text: list[str] = []
        self.in_title = False
        self.ignored = 0
        self.active = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.ignored += 1
        if self.ignored:
            return
        if tag == "title":
            self.in_title = True
        if re.fullmatch(r"h[1-6]", tag):
            self.heading_level = int(tag[1])
            self.heading_text = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.ignored = max(0, self.ignored - 1)
            return
        if self.ignored:
            return
        if tag == "title":
            self.in_title = False
        if self.heading_level and tag == f"h{self.heading_level}":
            self.active = {"level": self.heading_level,
                           "heading": "".join(self.heading_text).strip(), "nodes": []}
            self.blocks.append(self.active)
            self.heading_level = 0

    def handle_data(self, data):
        if self.ignored:
            return
        self.text.append(data)
        if self.in_title:
            self.title.append(data)
        if self.heading_level:
            self.heading_text.append(data)
        elif self.active is not None:
            self.active["nodes"].append(data)


def extract_evidence(html: str, card: dict[str, Any], skills: dict[str, str], url: str):
    if not source_url(url):
        return None
    page = SkillPage()
    page.feed(html)
    title = "".join(page.title).strip()
    rarity = card["rarity"]
    # R must not match SR/SSR; require the character, rarity and exact card title.
    if (normalize(card["char"]) not in normalize(title)
            or not re.search(rf"(?<![A-Z]){re.escape(rarity)}(?![A-Z])", unicodedata.normalize("NFKC", title))
            or normalize(card["card"]) not in normalize("".join(page.text))):
        return None
    known = {normalize(name): name for name in skills.values()}
    found: dict[str, list[str]] = {}
    for block in page.blocks:
        if normalize(block["heading"]) not in {normalize(h) for h in SKILL_HEADINGS}:
            continue
        for node in block["nodes"]:
            label = normalize(node)
            label = re.sub(r"\((?:レア|金スキル)\)$", "", label)
            # Exact text nodes only: avoid substring matches and prose/navigation.
            if label in known:
                found.setdefault(known[label], [])
                if block["heading"] not in found[known[label]]:
                    found[known[label]].append(block["heading"])
    if not found:
        return None
    return {"url": url, "title": title,
            "skills": [{"name": name, "section": sections} for name, sections in sorted(found.items())]}


def fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ja"})
    with urllib.request.urlopen(request, timeout=15) as response:
        # Do not follow source-page redirects to other hosts.
        if source_url(url) and not source_url(response.url):
            raise ValueError("Source redirected outside supported sites")
        if response.status != 200:
            raise ValueError(f"HTTP {response.status}")
        data = response.read(3_000_001)
        if len(data) > 3_000_000:
            raise ValueError("Response too large")
        return data.decode("utf-8")


def research_card(card: dict[str, Any], skills: dict[str, str], fetch=fetch_html):
    query = f"ウマ娘 {card['char']} {card['card']} {card['rarity']} サポート スキル"
    search = "https://search.yahoo.co.jp/search?" + urllib.parse.urlencode({"p": query})
    entry = {"source_id": str(card["source_id"]), "name": card["name"], "query": query,
             "search_url": search, "searches": [{"query": query, "url": search}], "status": "not_found", "candidates": [], "evidence": [], "errors": []}
    queries = [query, f"ウマ娘 {card['char']} {card['rarity']} スキル",
               f"{card['char']} スキル ウマ娘"]
    entry["searches"] = []
    visited = set()
    successful_search = False
    for attempt in queries:
        search = "https://search.yahoo.co.jp/search?" + urllib.parse.urlencode({"p": attempt})
        entry["searches"].append({"query": attempt, "url": search})
        try:
            links = SearchLinks()
            links.feed(fetch(search))
            successful_search = True
        except (OSError, ValueError, UnicodeError) as error:
            entry["errors"].append({"url": search, "error": type(error).__name__})
            continue
        # Broader fallback queries still require the exact card identity below.
        for url in links.links[:6]:
            if url in visited:
                continue
            visited.add(url)
            try:
                evidence = extract_evidence(fetch(url), card, skills, url)
                if evidence:
                    entry["evidence"].append(evidence)
            except (OSError, ValueError, UnicodeError) as error:
                entry["errors"].append({"url": url, "error": type(error).__name__})
        if entry["evidence"]:
            break
    if not successful_search:
        entry["status"] = "search_failed"
        return entry
    entry["evidence"].sort(key=lambda evidence: evidence["url"])
    entry["errors"].sort(key=lambda error: (error["url"], error["error"]))
    candidates: dict[str, set[str]] = {}
    for evidence in entry["evidence"]:
        for skill in evidence["skills"]:
            candidates.setdefault(skill["name"], set()).add(evidence["url"])
    entry["candidates"] = [{"name": name, "sources": sorted(urls)} for name, urls in sorted(candidates.items())]
    entry["status"] = "needs_review" if candidates else ("fetch_failed" if entry["errors"] else "not_found")
    return entry


def research_missing(import_report, cards, skills, previous=None, fetch=fetch_html):
    by_id = {str(card.get("source_id") or card.get("id", "")): card for card in cards}
    old = {c["source_id"]: c for c in (previous or {}).get("cards", [])}
    results = []
    for missing in import_report["missing_skill_cards"]:
        card_id = str(missing["source_id"])
        card = by_id.get(card_id)
        if card is None:
            raise ValueError(f"Missing card metadata: {card_id}")
        if card.get("skills"):
            continue
        entry = research_card(card, skills, fetch)
        # Preserve previous findings separately on failure; never mark them as fresh.
        if entry["errors"] and card_id in old:
            prior = old[card_id]
            prior_evidence = prior.get("evidence") or prior.get("previous_evidence", [])
            if prior_evidence:
                entry["previous_evidence"] = prior_evidence
        results.append(entry)
    report = {"schema_version": 1, "automatic_application": False,
              "cards": sorted(results, key=lambda c: c["source_id"])}
    current = {c["source_id"]: c for c in results}
    changes = {"added": sorted(current.keys() - old.keys()),
               "changed": sorted(k for k in current.keys() & old.keys() if current[k] != old[k]),
               "resolved": sorted(old.keys() - current.keys())}
    return report, changes


def markdown_report(report, changes):
    lines = ["## 未収録サポカの再検索", "", "候補は未承認です。カードデータには自動反映していません。", "",
             f"対象 {len(report['cards'])}枚 / 新規 {len(changes['added'])} / 変化 {len(changes['changed'])} / 対象外になったカード {len(changes['resolved'])}", ""]
    for card in report["cards"]:
        # Escape source text so it cannot inject headings, links or summary HTML.
        name = card["name"].replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ").replace("[", "\\[").replace("]", "\\]")
        lines.extend([f"### {name} ({card['source_id']})", "", f"状態: {card['status']}", ""])
        for skill in card["candidates"]:
            lines.append(f"- {skill['name']}")
        for evidence in card["evidence"]:
            lines.append(f"- 根拠: <{evidence['url']}>")
        if card["errors"]:
            lines.append("- 一部の検索・ページ取得に失敗しました。JSONのerrorsを確認してください。")
        if card.get("previous_evidence"):
            lines.append("- 前回の根拠をJSONに保持しています。今回の確認結果とは別扱いです。")
        if not card["candidates"]:
            lines.append("- 候補未取得。次回のデータ更新時に再検索します。")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-report", required=True, type=Path)
    parser.add_argument("--skills", required=True, type=Path)
    parser.add_argument("--cards-json", type=Path, default=ROOT / "frontend/src/data/cards.json")
    parser.add_argument("--report-json", type=Path, default=ROOT / "backend/data/missing_skill_research.json")
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    # Only normal/gold skill names are candidates, not unique/evolved skills.
    raw_skills = [s for s in as_records(read_json(args.skills)) if str(s.get("rarity")) in ("1", "2")]
    previous = read_json(args.report_json) if args.report_json.exists() else None
    report, changes = research_missing(read_json(args.import_report), read_json(args.cards_json),
                                       make_skill_map(raw_skills), previous)
    if args.report_json.resolve() in (args.cards_json.resolve(), args.skills.resolve(), args.import_report.resolve()):
        raise ValueError("Research output must not overwrite input data")
    if args.summary.resolve() in (args.cards_json.resolve(), args.skills.resolve(), args.import_report.resolve(), args.report_json.resolve()):
        raise ValueError("Summary output must not overwrite data")
    write_json(args.report_json, report)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(markdown_report(report, changes), encoding="utf-8")
    print(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "target_count": len(report["cards"]),
                      "changes": changes, "report": str(args.report_json)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
