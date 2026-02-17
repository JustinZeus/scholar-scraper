#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

ROBOTS_URL = "https://scholar.google.com/robots.txt"
PROFILE_URL = "https://scholar.google.com/citations"

DEFAULT_USER_AGENTS = [
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.1 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) "
        "Gecko/20100101 Firefox/131.0"
    ),
]

BLOCKED_KEYWORDS = [
    "unusual traffic",
    "sorry/index",
    "not a robot",
    "our systems have detected",
    "automated queries",
]

NO_RESULTS_KEYWORDS = [
    "didn't match any articles",
    "did not match any articles",
    "no articles",
    "no documents",
]

MARKER_KEYS = [
    "gsc_a_tr",
    "gsc_a_at",
    "gsc_a_ac",
    "gsc_a_h",
    "gsc_a_y",
    "gs_gray",
    "gsc_prf_in",
    "gsc_rsb_st",
]


@dataclass
class FetchRecord:
    source: str
    url: str
    file_name: str
    status_code: int | None
    fetched_at_utc: str
    elapsed_seconds: float
    final_url: str | None
    error: str | None


@dataclass
class PublicationCandidate:
    title: str
    title_url: str | None
    cluster_id: str | None
    year: int | None
    citation_count: int | None
    authors_text: str | None
    venue_text: str | None


@dataclass
class PageAnalysis:
    source: str
    status: str
    profile_name: str | None
    publication_count: int
    articles_range: str | None
    has_show_more_button: bool
    has_operation_error_banner: bool
    marker_counts: dict[str, int]
    field_presence: dict[str, int]
    parse_warnings: list[str]


def normalize_space(value: str) -> str:
    return " ".join(unescape(value).split())


TAG_RE = re.compile(r"<[^>]+>", re.S)


def strip_tags(value: str) -> str:
    return normalize_space(TAG_RE.sub(" ", value))


def attr_class(attrs: list[tuple[str, str | None]]) -> str:
    for name, raw_value in attrs:
        if name.lower() == "class":
            return raw_value or ""
    return ""


def attr_href(attrs: list[tuple[str, str | None]]) -> str | None:
    for name, raw_value in attrs:
        if name.lower() == "href":
            return raw_value
    return None


class ScholarRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_href: str | None = None
        self.title_parts: list[str] = []
        self.citation_parts: list[str] = []
        self.year_parts: list[str] = []
        self.gray_texts: list[str] = []

        self._title_depth = 0
        self._citation_depth = 0
        self._year_depth = 0
        self._gray_stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._title_depth > 0:
            self._title_depth += 1
        if self._citation_depth > 0:
            self._citation_depth += 1
        if self._year_depth > 0:
            self._year_depth += 1
        if self._gray_stack:
            self._gray_stack[-1]["depth"] += 1

        classes = attr_class(attrs)

        if tag == "a" and "gsc_a_at" in classes:
            self._title_depth = 1
            self.title_href = attr_href(attrs)
            return

        if tag == "a" and "gsc_a_ac" in classes:
            self._citation_depth = 1
            return

        if tag in {"span", "a"} and ("gsc_a_h" in classes or "gsc_a_y" in classes):
            self._year_depth = 1
            return

        if tag == "div" and "gs_gray" in classes:
            self._gray_stack.append({"depth": 1, "parts": []})
            return

    def handle_data(self, data: str) -> None:
        if self._title_depth > 0:
            self.title_parts.append(data)
        if self._citation_depth > 0:
            self.citation_parts.append(data)
        if self._year_depth > 0:
            self.year_parts.append(data)
        if self._gray_stack:
            self._gray_stack[-1]["parts"].append(data)

    def handle_endtag(self, _tag: str) -> None:
        if self._title_depth > 0:
            self._title_depth -= 1
        if self._citation_depth > 0:
            self._citation_depth -= 1
        if self._year_depth > 0:
            self._year_depth -= 1
        if self._gray_stack:
            self._gray_stack[-1]["depth"] -= 1
            if self._gray_stack[-1]["depth"] == 0:
                text = normalize_space("".join(self._gray_stack[-1]["parts"]))
                if text:
                    self.gray_texts.append(text)
                self._gray_stack.pop()


def extract_rows(html: str) -> list[str]:
    pattern = re.compile(
        r"<tr\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*\bgsc_a_tr\b[^'\"]*['\"])[^>]*>(.*?)</tr>",
        re.I | re.S,
    )
    return [match.group(1) for match in pattern.finditer(html)]


def parse_cluster_id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    parsed = urlparse(href)
    query = parse_qs(parsed.query)

    citation_for_view = query.get("citation_for_view")
    if citation_for_view:
        token = citation_for_view[0].strip()
        if token:
            if ":" in token:
                return token.rsplit(":", 1)[-1] or None
            return token

    cluster = query.get("cluster")
    if cluster:
        token = cluster[0].strip()
        if token:
            return token
    return None


def parse_year(parts: list[str]) -> int | None:
    text = normalize_space(" ".join(parts))
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def parse_citation_count(parts: list[str]) -> int | None:
    text = normalize_space(" ".join(parts))
    if not text:
        return 0
    match = re.search(r"\d+", text)
    if not match:
        return None
    return int(match.group(0))


def parse_publications(html: str) -> tuple[list[PublicationCandidate], list[str]]:
    rows = extract_rows(html)
    warnings: list[str] = []
    publications: list[PublicationCandidate] = []

    for row_html in rows:
        parser = ScholarRowParser()
        parser.feed(row_html)

        title = normalize_space("".join(parser.title_parts))
        if not title:
            warnings.append("row_missing_title")
            continue

        authors_text = parser.gray_texts[0] if len(parser.gray_texts) > 0 else None
        venue_text = parser.gray_texts[1] if len(parser.gray_texts) > 1 else None

        publications.append(
            PublicationCandidate(
                title=title,
                title_url=parser.title_href,
                cluster_id=parse_cluster_id_from_href(parser.title_href),
                year=parse_year(parser.year_parts),
                citation_count=parse_citation_count(parser.citation_parts),
                authors_text=authors_text,
                venue_text=venue_text,
            )
        )

    if not rows:
        warnings.append("no_rows_detected")

    return publications, sorted(set(warnings))


def extract_profile_name(html: str) -> str | None:
    pattern = re.compile(
        r"<[^>]*\bid\s*=\s*['\"]gsc_prf_in['\"][^>]*>(.*?)</[^>]+>",
        re.I | re.S,
    )
    match = pattern.search(html)
    if not match:
        return None
    value = strip_tags(match.group(1))
    return value or None


def extract_articles_range(html: str) -> str | None:
    pattern = re.compile(
        r"<[^>]*\bid\s*=\s*['\"]gsc_a_nn['\"][^>]*>(.*?)</[^>]+>",
        re.I | re.S,
    )
    match = pattern.search(html)
    if not match:
        return None
    value = strip_tags(match.group(1))
    return value or None


def has_show_more_button(html: str) -> bool:
    lowered = html.lower()
    return "id=\"gsc_bpf_more\"" in lowered or "id='gsc_bpf_more'" in lowered


def has_operation_error_banner(html: str) -> bool:
    lowered = html.lower()
    if "id=\"gsc_a_err\"" not in lowered and "id='gsc_a_err'" not in lowered:
        return False
    return "can't perform the operation now" in lowered or "cannot perform the operation now" in lowered


def count_markers(html: str) -> dict[str, int]:
    lowered = html.lower()
    return {key: lowered.count(key.lower()) for key in MARKER_KEYS}


def detect_status(
    *,
    status_code: int | None,
    final_url: str | None,
    html: str,
    publication_count: int,
    marker_counts: dict[str, int],
) -> str:
    if status_code is None:
        return "network_error"

    lowered = html.lower()
    final = (final_url or "").lower()

    if "accounts.google.com" in final and ("signin" in final or "servicelogin" in final):
        return "blocked_or_captcha"

    if any(keyword in lowered for keyword in BLOCKED_KEYWORDS) or "sorry/index" in final:
        return "blocked_or_captcha"

    if publication_count == 0 and any(keyword in lowered for keyword in NO_RESULTS_KEYWORDS):
        return "no_results"

    if publication_count == 0:
        has_profile_markers = marker_counts.get("gsc_prf_in", 0) > 0
        has_table_markers = marker_counts.get("gsc_a_tr", 0) > 0 or marker_counts.get("gsc_a_at", 0) > 0
        if not has_profile_markers and not has_table_markers:
            return "layout_changed"

    return "ok"


def load_scholar_ids(id_file: Path | None, cli_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    collected: list[str] = []

    def maybe_add(raw: str) -> None:
        item = raw.strip()
        if not item:
            return
        if item.startswith("#"):
            return
        if item in seen:
            return
        seen.add(item)
        collected.append(item)

    for item in cli_ids:
        maybe_add(item)

    if id_file and id_file.exists():
        for line in id_file.read_text(encoding="utf-8").splitlines():
            maybe_add(line)

    return collected


def fetch_url(url: str, user_agent: str, timeout_seconds: float) -> tuple[int | None, str | None, str, str | None]:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "close",
        },
    )
    start = time.perf_counter()

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            elapsed = time.perf_counter() - start
            status = getattr(response, "status", 200)
            final_url = response.geturl()
            return status, final_url, body, None
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        elapsed = time.perf_counter() - start
        _ = elapsed
        return exc.code, exc.geturl(), body, str(exc)
    except URLError as exc:
        elapsed = time.perf_counter() - start
        _ = elapsed
        return None, None, "", str(exc)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def render_markdown(
    *,
    generated_at: str,
    run_dir: Path,
    fetch_records: list[FetchRecord],
    page_analyses: list[PageAnalysis],
    publications_by_source: dict[str, list[PublicationCandidate]],
    robots_excerpt: str,
) -> str:
    lines: list[str] = []
    lines.append("# Scholar Scrape Probe Report")
    lines.append("")
    lines.append(f"Generated UTC: `{generated_at}`")
    lines.append(f"Run fixtures dir: `{run_dir.as_posix()}`")
    lines.append("")

    lines.append("## Robots Snapshot")
    lines.append("")
    lines.append("```text")
    lines.append(robots_excerpt.rstrip() or "(robots fetch unavailable)")
    lines.append("```")
    lines.append("")

    lines.append("## Fetch Summary")
    lines.append("")
    lines.append("| Source | Status Code | Status/Error | Final URL |")
    lines.append("| --- | --- | --- | --- |")
    for record in fetch_records:
        status = str(record.status_code) if record.status_code is not None else "-"
        state = record.error or "ok"
        final_url = record.final_url or "-"
        lines.append(f"| `{record.source}` | {status} | {state} | `{final_url}` |")
    lines.append("")

    lines.append("## Parse Summary")
    lines.append("")
    lines.append("| Source | Parse Status | Profile | Publications | Articles Range | Show More | Warnings |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for analysis in page_analyses:
        warnings = ", ".join(analysis.parse_warnings) if analysis.parse_warnings else "-"
        profile = analysis.profile_name or "-"
        articles_range = analysis.articles_range or "-"
        show_more = "yes" if analysis.has_show_more_button else "no"
        lines.append(
            f"| `{analysis.source}` | `{analysis.status}` | {profile} | {analysis.publication_count} | {articles_range} | {show_more} | {warnings} |"
        )
    lines.append("")

    all_publications = [
        publication
        for publications in publications_by_source.values()
        for publication in publications
    ]

    if all_publications:
        total = len(all_publications)
        def pct(count: int) -> str:
            return f"{(count / total) * 100:.1f}%"

        title_count = sum(1 for item in all_publications if item.title)
        cluster_count = sum(1 for item in all_publications if item.cluster_id)
        year_count = sum(1 for item in all_publications if item.year is not None)
        citation_count = sum(1 for item in all_publications if item.citation_count is not None)
        author_count = sum(1 for item in all_publications if item.authors_text)
        venue_count = sum(1 for item in all_publications if item.venue_text)

        lines.append("## Field Coverage")
        lines.append("")
        lines.append(f"Total parsed publication rows: **{total}**")
        lines.append("")
        lines.append("| Field | Present | Coverage |")
        lines.append("| --- | --- | --- |")
        lines.append(f"| `title` | {title_count} | {pct(title_count)} |")
        lines.append(f"| `cluster_id` | {cluster_count} | {pct(cluster_count)} |")
        lines.append(f"| `year` | {year_count} | {pct(year_count)} |")
        lines.append(f"| `citation_count` | {citation_count} | {pct(citation_count)} |")
        lines.append(f"| `authors_text` | {author_count} | {pct(author_count)} |")
        lines.append(f"| `venue_text` | {venue_count} | {pct(venue_count)} |")
        lines.append("")

    lines.append("## Parser Contract Recommendation")
    lines.append("")
    lines.append("- Primary row marker: `tr.gsc_a_tr`.")
    lines.append("- Title anchor marker: `a.gsc_a_at`; derive `cluster_id` from `citation_for_view` query token.")
    lines.append("- Metadata text markers: first/second `div.gs_gray` per row for authors and venue.")
    lines.append("- Year marker fallback: classes containing `gsc_a_h` or `gsc_a_y` and 4-digit year regex.")
    lines.append("- Failure states to persist: `ok`, `no_results`, `blocked_or_captcha`, `layout_changed`, `network_error`.")
    lines.append("")

    lines.append("## Future-Proofing Notes")
    lines.append("")
    lines.append("- Keep raw HTML fixture snapshots and update parser tests on DOM drift.")
    lines.append("- Treat blocked pages as retriable with backoff, not parser errors.")
    lines.append("- If `Show more` is present, treat first-page-only results as partial and surface that in run status/UI.")
    lines.append("- Track robots policy changes because `/citations?*cstart=` is currently disallowed.")
    lines.append("- Add marker-count assertions in CI to catch silent layout shifts early.")
    lines.append("- Use explicit parse status per run/scholar so automation can degrade gracefully.")

    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Temporary probe: capture and analyze Google Scholar profile HTML for parser planning."
    )
    parser.add_argument(
        "--output-root",
        default="planning/scholar_probe_tmp",
        help="Root directory of temporary probe workspace.",
    )
    parser.add_argument(
        "--scholar-id",
        action="append",
        default=[],
        help="Scholar profile id (can be passed multiple times).",
    )
    parser.add_argument(
        "--id-file",
        default="planning/scholar_probe_tmp/notes/seed_scholar_ids.txt",
        help="Path to newline-delimited scholar ids.",
    )
    parser.add_argument(
        "--max-profiles",
        type=int,
        default=5,
        help="Maximum number of scholar profiles to fetch in this probe run.",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=8.0,
        help="Base delay between live requests.",
    )
    parser.add_argument(
        "--request-jitter-seconds",
        type=float,
        default=2.0,
        help="Randomized additional delay in seconds.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=25.0,
        help="HTTP timeout seconds.",
    )
    parser.add_argument(
        "--allow-live-fetch",
        action="store_true",
        help="Enable outbound fetch for robots and scholar profile pages.",
    )
    parser.add_argument(
        "--analyze-existing-fixtures",
        action="store_true",
        help="Analyze existing fixtures in output-root/fixtures even if live fetch is disabled.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    output_root = Path(args.output_root)
    fixtures_root = output_root / "fixtures"
    notes_root = output_root / "notes"
    fixtures_root.mkdir(parents=True, exist_ok=True)
    notes_root.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    run_id = now.strftime("run_%Y%m%dT%H%M%SZ")
    run_dir = fixtures_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    id_file = Path(args.id_file)
    scholar_ids = load_scholar_ids(id_file, args.scholar_id)
    if args.max_profiles > 0:
        scholar_ids = scholar_ids[: args.max_profiles]

    fetch_records: list[FetchRecord] = []
    robots_excerpt = ""

    if args.allow_live_fetch:
        robots_start = time.perf_counter()
        robots_status, robots_final_url, robots_body, robots_error = fetch_url(
            ROBOTS_URL,
            user_agent=random.choice(DEFAULT_USER_AGENTS),
            timeout_seconds=args.timeout_seconds,
        )
        robots_elapsed = time.perf_counter() - robots_start

        robots_path = run_dir / "robots.txt"
        robots_path.write_text(robots_body or "", encoding="utf-8")
        robots_excerpt = "\n".join((robots_body or "").splitlines()[:50])

        fetch_records.append(
            FetchRecord(
                source="robots",
                url=ROBOTS_URL,
                file_name=robots_path.name,
                status_code=robots_status,
                fetched_at_utc=datetime.now(timezone.utc).isoformat(),
                elapsed_seconds=round(robots_elapsed, 3),
                final_url=robots_final_url,
                error=robots_error,
            )
        )

        for index, scholar_id in enumerate(scholar_ids):
            params = {"hl": "en", "user": scholar_id}
            url = f"{PROFILE_URL}?{urlencode(params)}"

            user_agent = DEFAULT_USER_AGENTS[index % len(DEFAULT_USER_AGENTS)]
            start = time.perf_counter()
            status_code, final_url, body, error = fetch_url(
                url,
                user_agent=user_agent,
                timeout_seconds=args.timeout_seconds,
            )
            elapsed = time.perf_counter() - start

            safe_source = f"profile_{scholar_id}"
            html_name = f"{safe_source}.html"
            html_path = run_dir / html_name
            html_path.write_text(body or "", encoding="utf-8")

            fetch_records.append(
                FetchRecord(
                    source=safe_source,
                    url=url,
                    file_name=html_name,
                    status_code=status_code,
                    fetched_at_utc=datetime.now(timezone.utc).isoformat(),
                    elapsed_seconds=round(elapsed, 3),
                    final_url=final_url,
                    error=error,
                )
            )

            if index < len(scholar_ids) - 1:
                delay = max(0.0, args.request_delay_seconds) + random.uniform(
                    0.0,
                    max(0.0, args.request_jitter_seconds),
                )
                time.sleep(delay)

    if not robots_excerpt:
        robots_candidates = sorted(fixtures_root.glob("run_*/robots.txt"), reverse=True)
        if robots_candidates:
            robots_excerpt = "\n".join(
                robots_candidates[0].read_text(encoding="utf-8").splitlines()[:50]
            )

    html_files: list[Path] = []
    html_files.extend(run_dir.glob("profile_*.html"))

    if args.analyze_existing_fixtures:
        latest_runs = sorted(fixtures_root.glob("run_*"), reverse=True)
        for existing_run in latest_runs:
            if existing_run == run_dir:
                continue
            html_files.extend(existing_run.glob("profile_*.html"))

    by_source: dict[str, Path] = {}
    for candidate in sorted(html_files, reverse=True):
        source = candidate.stem
        if source in by_source:
            continue
        by_source[source] = candidate
    deduped_files = [by_source[source] for source in sorted(by_source)]

    page_analyses: list[PageAnalysis] = []
    publications_by_source: dict[str, list[PublicationCandidate]] = {}

    fetch_record_by_source = {record.source: record for record in fetch_records}

    for html_path in deduped_files:
        source = html_path.stem
        html = html_path.read_text(encoding="utf-8")
        publications, warnings = parse_publications(html)
        markers = count_markers(html)
        articles_range = extract_articles_range(html)
        show_more = has_show_more_button(html)
        operation_error_banner = has_operation_error_banner(html)

        if show_more:
            warnings.append("possible_partial_page_show_more_present")
        if operation_error_banner:
            warnings.append("operation_error_banner_present")
        warnings = sorted(set(warnings))

        record = fetch_record_by_source.get(source)
        status = detect_status(
            status_code=record.status_code if record else 200,
            final_url=record.final_url if record else None,
            html=html,
            publication_count=len(publications),
            marker_counts=markers,
        )

        field_presence = {
            "title": sum(1 for item in publications if item.title),
            "cluster_id": sum(1 for item in publications if item.cluster_id),
            "year": sum(1 for item in publications if item.year is not None),
            "citation_count": sum(1 for item in publications if item.citation_count is not None),
            "authors_text": sum(1 for item in publications if item.authors_text),
            "venue_text": sum(1 for item in publications if item.venue_text),
        }

        analysis = PageAnalysis(
            source=source,
            status=status,
            profile_name=extract_profile_name(html),
            publication_count=len(publications),
            articles_range=articles_range,
            has_show_more_button=show_more,
            has_operation_error_banner=operation_error_banner,
            marker_counts=markers,
            field_presence=field_presence,
            parse_warnings=warnings,
        )
        page_analyses.append(analysis)
        publications_by_source[source] = publications

    report_payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_dir": run_dir.as_posix(),
        "fetch_records": [asdict(record) for record in fetch_records],
        "page_analyses": [asdict(analysis) for analysis in page_analyses],
        "publications_by_source": {
            source: [asdict(item) for item in publications]
            for source, publications in publications_by_source.items()
        },
    }

    json_report_path = notes_root / f"probe_report_{run_id}.json"
    write_json(json_report_path, report_payload)

    markdown_report = render_markdown(
        generated_at=report_payload["generated_at_utc"],
        run_dir=run_dir,
        fetch_records=fetch_records,
        page_analyses=page_analyses,
        publications_by_source=publications_by_source,
        robots_excerpt=robots_excerpt,
    )
    markdown_report_path = notes_root / f"probe_report_{run_id}.md"
    markdown_report_path.write_text(markdown_report, encoding="utf-8")

    summary = {
        "run_id": run_id,
        "run_dir": run_dir.as_posix(),
        "json_report": json_report_path.as_posix(),
        "markdown_report": markdown_report_path.as_posix(),
        "profiles_analyzed": len(page_analyses),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
