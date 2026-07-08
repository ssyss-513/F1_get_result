#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
F1_BASE_URL = "https://www.formula1.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


SESSION_PATHS = {
    "practice-1": "practice/1",
    "practice-2": "practice/2",
    "practice-3": "practice/3",
    "sprint-qualifying": "sprint-qualifying",
    "sprint": "sprint-results",
    "qualifying": "qualifying",
    "race": "race-result",
}


SESSION_FILE_NAMES = {
    "practice-1": "practice-1",
    "practice-2": "practice-2",
    "practice-3": "practice-3",
    "sprint-qualifying": "sprint-qualifying",
    "sprint": "sprint",
    "qualifying": "qualifying",
    "race": "race",
}


@dataclasses.dataclass(frozen=True)
class CalendarEvent:
    uid: str
    summary: str
    location: str
    start: dt.datetime
    end: dt.datetime
    year: int
    race_title: str
    session_key: str


@dataclasses.dataclass(frozen=True)
class RaceInfo:
    year: int
    race_id: str
    slug: str
    name: str
    title: str


@dataclasses.dataclass(frozen=True)
class ResultTable:
    headers: list[str]
    rows: list[list[str]]


class TableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[ResultTable] = []
        self._in_table = False
        self._in_row = False
        self._cell_tag: Optional[str] = None
        self._current_headers: list[str] = []
        self._current_rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self._row_has_header = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        classes = set(attrs_dict.get("class", "").split())

        if self._cell_tag is not None and "md:hidden" in classes:
            self._skip_depth += 1

        if tag == "table":
            self._in_table = True
            self._current_headers = []
            self._current_rows = []
            return

        if not self._in_table:
            return

        if tag == "tr":
            self._in_row = True
            self._current_row = []
            self._row_has_header = False
            return

        if tag in {"td", "th"} and self._in_row:
            self._cell_tag = tag
            self._current_cell = []
            if tag == "th":
                self._row_has_header = True

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth and self._cell_tag is not None:
            self._skip_depth -= 1
            return

        if tag in {"td", "th"} and self._cell_tag == tag:
            text = clean_text(" ".join(self._current_cell))
            self._current_row.append(text)
            self._cell_tag = None
            self._current_cell = []
            return

        if tag == "tr" and self._in_row:
            row = [cell for cell in self._current_row if cell != ""]
            if row:
                if self._row_has_header and not self._current_headers:
                    self._current_headers = self._current_row
                elif not self._row_has_header:
                    self._current_rows.append(self._current_row)
            self._in_row = False
            self._current_row = []
            return

        if tag == "table" and self._in_table:
            headers = [clean_text(cell) for cell in self._current_headers]
            rows = [[clean_text(cell) for cell in row] for row in self._current_rows]
            if headers and rows:
                self.tables.append(ResultTable(headers=headers, rows=rows))
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._cell_tag is not None and self._skip_depth == 0:
            self._current_cell.append(data)


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_url(url: str, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_ics(ics_file: Optional[str], ics_url: Optional[str]) -> str:
    if ics_file:
        return Path(ics_file).read_text(encoding="utf-8-sig")
    if ics_url:
        return fetch_url(ics_url)
    env_url = os.environ.get("F1_ICS_URL", "").strip()
    if env_url:
        return fetch_url(env_url)
    default_file = BASE_DIR / "data" / "Formula_1.ics"
    if default_file.is_file():
        return default_file.read_text(encoding="utf-8-sig")
    raise SystemExit("No ICS source. Use --ics-file, --ics-url, F1_ICS_URL, or F1_get_result/data/Formula_1.ics.")


def unfold_ics_lines(content: str) -> list[str]:
    unfolded: list[str] = []
    for raw in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += raw[1:]
        elif raw:
            unfolded.append(raw)
    return unfolded


def parse_ics_datetime(value: str) -> dt.datetime:
    if value.endswith("Z"):
        return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    if "T" in value:
        return dt.datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc)
    return dt.datetime.strptime(value, "%Y%m%d").replace(tzinfo=dt.timezone.utc)


def parse_ics_text(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def parse_ics_events(content: str) -> list[dict[str, str]]:
    lines = unfold_ics_lines(content)
    events: list[dict[str, str]] = []
    current: Optional[dict[str, str]] = None

    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.split(";", 1)[0].upper()
        current[key] = parse_ics_text(value)

    return events


def normalize_session(summary: str) -> Optional[str]:
    session = summary.rsplit(" - ", 1)[-1].strip().lower()
    if "practice 1" in session:
        return "practice-1"
    if "practice 2" in session:
        return "practice-2"
    if "practice 3" in session:
        return "practice-3"
    if "sprint qualific" in session or "sprint shootout" in session:
        return "sprint-qualifying"
    if "sprint race" in session or session == "sprint":
        return "sprint"
    if "qualifying" in session:
        return "qualifying"
    if session == "race" or session.endswith(" race"):
        return "race"
    return None


def extract_race_title(summary: str) -> str:
    left = summary.rsplit(" - ", 1)[0]
    left = re.sub(r"^[^\w]*\s*", "", left, flags=re.UNICODE)
    left = re.sub(r"^FORMULA 1\s+", "", left, flags=re.IGNORECASE)
    return clean_text(left)


def calendar_events_from_ics(content: str) -> list[CalendarEvent]:
    parsed = parse_ics_events(content)
    events: list[CalendarEvent] = []
    for event in parsed:
        summary = event.get("SUMMARY", "")
        session_key = normalize_session(summary)
        if not session_key:
            continue
        try:
            start = parse_ics_datetime(event["DTSTART"])
            end = parse_ics_datetime(event["DTEND"])
        except (KeyError, ValueError):
            continue
        events.append(
            CalendarEvent(
                uid=event.get("UID", hashlib.sha1(summary.encode("utf-8")).hexdigest()),
                summary=summary,
                location=event.get("LOCATION", ""),
                start=start,
                end=end,
                year=start.year,
                race_title=extract_race_title(summary),
                session_key=session_key,
            )
        )
    return sorted(events, key=lambda item: item.start)


def normalize_for_match(value: str) -> str:
    value = clean_text(value).lower()
    value = value.replace("’", "'")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def discover_races(year: int) -> list[RaceInfo]:
    url = f"{F1_BASE_URL}/en/results/{year}/races"
    html_text = fetch_url(url)
    races: dict[tuple[str, str], RaceInfo] = {}

    schedule_pattern = re.compile(
        r'"url":"\\/en\\/racing\\/(?P<year>\d{4})\\/(?P<slug>[^"]+)".{0,1200}?'
        r'"text":"(?P<title>.*?)".{0,1200}?"meetingKey":"(?P<key>\d+)".{0,800}?"meetingName":"(?P<name>.*?)"',
        re.DOTALL,
    )
    for match in schedule_pattern.finditer(html_text):
        if int(match.group("year")) != year:
            continue
        slug = decode_jsonish(match.group("slug"))
        race = RaceInfo(
            year=year,
            race_id=match.group("key"),
            slug=slug,
            name=decode_jsonish(match.group("name")),
            title=decode_jsonish(match.group("title")),
        )
        races[(race.race_id, race.slug)] = race

    link_pattern = re.compile(rf"/en/results/{year}/races/(?P<key>\d+)/(?P<slug>[a-z0-9-]+)")
    for match in link_pattern.finditer(html_text):
        race_id = match.group("key")
        slug = match.group("slug")
        races.setdefault((race_id, slug), RaceInfo(year=year, race_id=race_id, slug=slug, name=slug, title=slug))

    return sorted(races.values(), key=lambda item: int(item.race_id))


def decode_jsonish(value: str) -> str:
    value = value.replace("\\u0026", "&")
    value = value.replace("\\/", "/")
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return html.unescape(value)


def load_aliases() -> dict[str, Any]:
    return read_json(BASE_DIR / "config" / "race_aliases.json", {})


def match_race(event: CalendarEvent, races: list[RaceInfo], aliases: dict[str, Any]) -> Optional[RaceInfo]:
    title_upper = event.race_title.upper()
    title_hints = aliases.get("title_slug_hints", {})
    for keyword, slug in title_hints.items():
        if keyword.upper() in title_upper:
            found = find_race_by_slug(races, slug)
            if found:
                return found

    location_hints = aliases.get("location_slug_hints", {}).get(event.location, [])
    for hint in location_hints:
        found = find_race_by_slug(races, hint)
        if found and (hint != "united-states" or "UNITED STATES" in title_upper):
            return found

    event_text = normalize_for_match(event.race_title + " " + event.location)
    best: Optional[RaceInfo] = None
    best_score = 0
    for race in races:
        candidates = [
            normalize_for_match(race.slug.replace("-", " ")),
            normalize_for_match(race.name),
            normalize_for_match(race.title),
        ]
        score = sum(1 for candidate in candidates if candidate and candidate in event_text)
        if score > best_score:
            best = race
            best_score = score
    return best if best_score > 0 else None


def find_race_by_slug(races: list[RaceInfo], slug_or_hint: str) -> Optional[RaceInfo]:
    needle = normalize_for_match(slug_or_hint.replace("-", " "))
    for race in races:
        haystacks = [
            normalize_for_match(race.slug.replace("-", " ")),
            normalize_for_match(race.name),
            normalize_for_match(race.title),
        ]
        if any(needle == hay or needle in hay for hay in haystacks):
            return race
    return None


def extract_tables(html_text: str) -> list[ResultTable]:
    parser = TableExtractor()
    parser.feed(html_text)
    return [table for table in parser.tables if looks_like_result_table(table)]


def looks_like_result_table(table: ResultTable) -> bool:
    headers = [header.upper() for header in table.headers]
    joined = " ".join(headers)
    if not table.rows:
        return False
    if len(table.rows) == 1 and table.rows[0] and re.search(r"no results available|error", table.rows[0][0], re.IGNORECASE):
        return False
    return ("POS" in joined or "POSITION" in joined) and ("DRIVER" in joined or "DRIVER" in joined) and (
        "CAR" in joined or "TEAM" in joined
    )


def fetch_result_table(race: RaceInfo, session_key: str) -> tuple[str, ResultTable]:
    path = SESSION_PATHS[session_key]
    url = f"{F1_BASE_URL}/en/results/{race.year}/races/{race.race_id}/{race.slug}/{path}"
    html_text = fetch_url(url)
    tables = extract_tables(html_text)
    if not tables:
        raise RuntimeError(f"No results table found at {url}")
    return url, tables[0]


def load_translations() -> dict[str, Any]:
    return read_json(BASE_DIR / "config" / "translations.json", {})


def translate(value: str, mapping: dict[str, str]) -> str:
    value = clean_text(value)
    return mapping.get(value, value)


def format_driver_name(value: str, mapping: dict[str, str]) -> str:
    value = clean_text(value)
    translated = mapping.get(value, value)
    if translated == value:
        return value
    return f"{translated} {value}"


def row_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    data: dict[str, str] = {}
    for index, header in enumerate(headers):
        key = normalize_header(header)
        data[key] = row[index] if index < len(row) else ""
    return data


def normalize_header(header: str) -> str:
    header = clean_text(header).upper()
    header = header.replace(".", "")
    if "TIME" in header and ("GAP" in header or "RETIRED" in header):
        return "time"
    aliases = {
        "POS": "pos",
        "POSITION": "pos",
        "NO": "no",
        "NUMBER": "no",
        "DRIVER": "driver",
        "CAR": "car",
        "TEAM": "car",
        "TIME": "time",
        "GAP": "gap",
        "LAPS": "laps",
        "PTS": "pts",
        "POINTS": "pts",
        "Q1": "q1",
        "Q2": "q2",
        "Q3": "q3",
        "SQ1": "sq1",
        "SQ2": "sq2",
        "SQ3": "sq3",
    }
    return aliases.get(header, header.lower())


def result_value(*values: str) -> str:
    for value in values:
        value = clean_text(value)
        if value and value != "-":
            return value
    return "-"


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|")


def markdown_table(headers: list[str], aligns: list[str], rows: list[list[str]]) -> str:
    separator = []
    for alignment in aligns:
        if alignment == "right":
            separator.append("---:")
        elif alignment == "center":
            separator.append(":---:")
        else:
            separator.append("---")
    lines = [
        "| " + " | ".join(markdown_escape(header) for header in headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_escape(cell) for cell in row) + " |")
    return "\n".join(lines)


def format_result_markdown(event: CalendarEvent, race: RaceInfo, source_url: str, table: ResultTable) -> str:
    translations = load_translations()
    driver_map = translations.get("drivers", {})
    team_map = translations.get("teams", {})
    session_zh = translations.get("sessions", {}).get(event.session_key, event.session_key)
    race_zh = translations.get("races_zh", {}).get(race.slug, f"{race.name}大奖赛")
    circuit_zh = translations.get("circuits_zh", {}).get(race.slug, "")

    rows_as_dicts = [row_dict(table.headers, row) for row in table.rows]

    if event.session_key.startswith("practice"):
        headers = ["名次", "车号", "车手", "车队", "时间/差距", "圈数"]
        aligns = ["right", "right", "left", "left", "right", "right"]
        rows = [
            [
                result_value(data.get("pos", "")),
                result_value(data.get("no", "")),
                format_driver_name(result_value(data.get("driver", "")), driver_map),
                translate(result_value(data.get("car", "")), team_map),
                result_value(data.get("time", ""), data.get("gap", "")),
                result_value(data.get("laps", "")),
            ]
            for data in rows_as_dicts
        ]
    elif event.session_key == "sprint-qualifying":
        headers = ["名次", "车号", "车手", "车队", "SQ1", "SQ2", "SQ3", "圈数"]
        aligns = ["right", "right", "left", "left", "right", "right", "right", "right"]
        rows = [
            [
                result_value(data.get("pos", "")),
                result_value(data.get("no", "")),
                format_driver_name(result_value(data.get("driver", "")), driver_map),
                translate(result_value(data.get("car", "")), team_map),
                result_value(data.get("sq1", ""), data.get("q1", "")),
                result_value(data.get("sq2", ""), data.get("q2", "")),
                result_value(data.get("sq3", ""), data.get("q3", "")),
                result_value(data.get("laps", "")),
            ]
            for data in rows_as_dicts
        ]
    elif event.session_key == "qualifying":
        headers = ["名次", "车号", "车手", "车队", "Q1", "Q2", "Q3", "圈数"]
        aligns = ["right", "right", "left", "left", "right", "right", "right", "right"]
        rows = [
            [
                result_value(data.get("pos", "")),
                result_value(data.get("no", "")),
                format_driver_name(result_value(data.get("driver", "")), driver_map),
                translate(result_value(data.get("car", "")), team_map),
                result_value(data.get("q1", "")),
                result_value(data.get("q2", "")),
                result_value(data.get("q3", "")),
                result_value(data.get("laps", "")),
            ]
            for data in rows_as_dicts
        ]
    else:
        headers = ["名次", "车号", "车手", "车队", "圈数", "时间/退赛", "积分"]
        aligns = ["right", "right", "left", "left", "right", "right", "right"]
        rows = [
            [
                result_value(data.get("pos", "")),
                result_value(data.get("no", "")),
                format_driver_name(result_value(data.get("driver", "")), driver_map),
                translate(result_value(data.get("car", "")), team_map),
                result_value(data.get("laps", "")),
                result_value(data.get("time", ""), data.get("gap", "")),
                result_value(data.get("pts", "")),
            ]
            for data in rows_as_dicts
        ]

    when = event.end.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    place = f"在{circuit_zh}进行" if circuit_zh else "进行"
    intro = f"{event.year}年{race_zh}{session_zh}{place}，以下为官方成绩："

    return "\n\n".join(
        [
            f"## {session_zh}",
            f"{intro}\n\n赛程时间：{when}",
            markdown_table(headers, aligns, rows),
            f"来源：[Formula 1 官方{session_zh}结果]({source_url})",
        ]
    ) + "\n"


def eligible_events(
    events: list[CalendarEvent],
    now: dt.datetime,
    lookback_hours: int,
    delay_minutes: int,
    force: bool,
) -> list[CalendarEvent]:
    if force:
        return events
    earliest = now - dt.timedelta(hours=lookback_hours)
    delay = dt.timedelta(minutes=delay_minutes)
    return [event for event in events if earliest <= event.end <= now - delay]


def load_state(path: Path) -> dict[str, Any]:
    return read_json(path, {"results": {}})


def state_key(race: RaceInfo, session_key: str) -> str:
    return f"{race.year}:{race.race_id}:{race.slug}:{session_key}"


def output_path(output_dir: Path, race: RaceInfo, session_key: str) -> Path:
    return output_dir / str(race.year) / f"{race.slug}-{SESSION_FILE_NAMES[session_key]}.md"


def parse_now(value: Optional[str]) -> dt.datetime:
    if not value:
        return dt.datetime.now(dt.timezone.utc)
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def list_events(events: list[CalendarEvent]) -> None:
    for event in events:
        print(
            f"{event.start.isoformat()} -> {event.end.isoformat()} | "
            f"{event.location} | {event.session_key} | {event.race_title}"
        )


def run(args: argparse.Namespace) -> int:
    ics_content = fetch_ics(args.ics_file, args.ics_url)
    events = calendar_events_from_ics(ics_content)

    if args.list_events:
        list_events(events)
        return 0

    now = parse_now(args.now)
    if args.year:
        events = [event for event in events if event.year == args.year]
    if args.session:
        events = [event for event in events if event.session_key == args.session]

    aliases = load_aliases()
    races_by_year: dict[int, list[RaceInfo]] = {}
    candidates = eligible_events(events, now, args.lookback_hours, args.delay_minutes, args.force)
    if args.race_slug:
        filtered_candidates = []
        for event in candidates:
            if args.race_id:
                forced = RaceInfo(
                    year=event.year,
                    race_id=args.race_id,
                    slug=args.race_slug,
                    name=args.race_slug,
                    title=args.race_slug,
                )
                matched = match_race(event, [forced], aliases)
            else:
                if event.year not in races_by_year:
                    try:
                        races_by_year[event.year] = discover_races(event.year)
                    except (HTTPError, URLError, TimeoutError) as exc:
                        print(f"warn: could not discover races for {event.year}: {exc}", file=sys.stderr)
                        continue
                matched = match_race(event, races_by_year[event.year], aliases)

            if matched is not None and matched.slug == args.race_slug:
                filtered_candidates.append(event)
        candidates = filtered_candidates

    state_path = Path(args.state_file)
    state = load_state(state_path)
    changed = False
    generated_count = 0

    for event in candidates:
        if args.race_slug:
            if args.race_id:
                race = RaceInfo(year=event.year, race_id=args.race_id, slug=args.race_slug, name=args.race_slug, title=event.race_title)
            else:
                if event.year not in races_by_year:
                    try:
                        races_by_year[event.year] = discover_races(event.year)
                    except (HTTPError, URLError, TimeoutError) as exc:
                        print(f"warn: could not discover races for {event.year}: {exc}", file=sys.stderr)
                        continue
                race = find_race_by_slug(races_by_year[event.year], args.race_slug)
                if race is None:
                    print(f"warn: could not find race slug {args.race_slug} for {event.year}", file=sys.stderr)
                    continue
        else:
            if event.year not in races_by_year:
                try:
                    races_by_year[event.year] = discover_races(event.year)
                except (HTTPError, URLError, TimeoutError) as exc:
                    print(f"warn: could not discover races for {event.year}: {exc}", file=sys.stderr)
                    continue
            race = match_race(event, races_by_year[event.year], aliases)
            if race is None:
                print(f"warn: could not match race for {event.summary}", file=sys.stderr)
                continue

        if not race.race_id:
            print(f"warn: race id is required for {race.slug}; pass --race-id or use discovery", file=sys.stderr)
            continue

        key = state_key(race, event.session_key)
        try:
            source_url, table = fetch_result_table(race, event.session_key)
            md = format_result_markdown(event, race, source_url, table)
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            print(f"info: result not ready for {key}: {exc}", file=sys.stderr)
            continue

        digest = hashlib.sha256(md.encode("utf-8")).hexdigest()
        if state["results"].get(key, {}).get("sha256") == digest and not args.force:
            print(f"unchanged: {key}")
            continue

        out = output_path(Path(args.output_dir), race, event.session_key)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        state["results"][key] = {
            "sha256": digest,
            "source_url": source_url,
            "output": str(out),
            "updated_at": now.isoformat(),
            "event_summary": event.summary,
        }
        changed = True
        generated_count += 1
        print(f"generated: {out}")
        if args.sleep_seconds:
            time.sleep(args.sleep_seconds)

    if changed and not args.no_state:
        write_json(state_path, state)

    print(f"done: generated {generated_count} file(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate blog-ready Markdown tables from official Formula 1 results.")
    parser.add_argument("--ics-file", help="Path to a Formula 1 ICS file.")
    parser.add_argument("--ics-url", help="Formula 1 ICS subscription URL. Prefer GitHub secret F1_ICS_URL.")
    parser.add_argument("--output-dir", default=str(BASE_DIR / "generated"), help="Markdown output directory.")
    parser.add_argument("--state-file", default=str(BASE_DIR / "state" / "results_state.json"), help="State JSON path.")
    parser.add_argument("--lookback-hours", type=int, default=96, help="Only process sessions ended within this many hours.")
    parser.add_argument("--delay-minutes", type=int, default=20, help="Wait this long after session end before fetching results.")
    parser.add_argument("--sleep-seconds", type=float, default=0.5, help="Delay between Formula 1 page requests.")
    parser.add_argument("--year", type=int, help="Limit to a season year.")
    parser.add_argument("--session", choices=sorted(SESSION_PATHS), help="Limit to one session key.")
    parser.add_argument("--race-slug", help="Force a Formula 1 result race slug, e.g. great-britain.")
    parser.add_argument("--race-id", help="Force a Formula 1 result race id, e.g. 1289.")
    parser.add_argument("--now", help="Override current time, ISO format, e.g. 2026-07-06T12:00:00Z.")
    parser.add_argument("--force", action="store_true", help="Process all filtered events and overwrite output/state.")
    parser.add_argument("--no-state", action="store_true", help="Do not write the state file.")
    parser.add_argument("--list-events", action="store_true", help="Only list parsed ICS sessions.")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
