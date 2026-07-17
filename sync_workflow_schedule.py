#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Iterable

from f1_get_result import BASE_DIR, CalendarEvent, calendar_events_from_ics, fetch_ics


START_MARKER = "    # BEGIN GENERATED F1 SESSION SCHEDULE"
END_MARKER = "    # END GENERATED F1 SESSION SCHEDULE"
DEFAULT_RETRY_MINUTES = (17, 47)


def build_schedule_entries(
    events: Iterable[CalendarEvent],
    retry_minutes: tuple[int, ...] = DEFAULT_RETRY_MINUTES,
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()

    for event in sorted(events, key=lambda item: item.end):
        end = event.end.astimezone(dt.timezone.utc)
        for minutes in retry_minutes:
            scheduled = end + dt.timedelta(minutes=minutes)
            cron = f"{scheduled.minute} {scheduled.hour} {scheduled.day} {scheduled.month} *"
            if cron in seen:
                continue
            seen.add(cron)
            label = f"{end:%Y-%m-%d} {event.session_key} +{minutes}m"
            entries.append((cron, label))

    return entries


def render_schedule_block(
    events: Iterable[CalendarEvent],
    retry_minutes: tuple[int, ...] = DEFAULT_RETRY_MINUTES,
) -> list[str]:
    lines = [
        START_MARKER,
        '    - cron: "17 4 * * *" # daily recovery',
    ]
    lines.extend(
        f'    - cron: "{cron}" # {label}'
        for cron, label in build_schedule_entries(events, retry_minutes)
    )
    lines.append(END_MARKER)
    return lines


def update_workflow(
    workflow_path: Path,
    events: Iterable[CalendarEvent],
    retry_minutes: tuple[int, ...] = DEFAULT_RETRY_MINUTES,
) -> bool:
    original = workflow_path.read_text(encoding="utf-8")
    lines = original.splitlines()
    try:
        start = lines.index(START_MARKER)
        end = lines.index(END_MARKER)
    except ValueError as exc:
        raise SystemExit(f"Schedule markers are missing from {workflow_path}") from exc
    if end < start:
        raise SystemExit(f"Schedule markers are out of order in {workflow_path}")

    updated_lines = lines[:start] + render_schedule_block(events, retry_minutes) + lines[end + 1 :]
    updated = "\n".join(updated_lines) + "\n"
    if updated == original:
        return False
    workflow_path.write_text(updated, encoding="utf-8")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate exact GitHub Actions schedules from an F1 ICS calendar.")
    parser.add_argument("--ics-file", help="Path to a Formula 1 ICS file.")
    parser.add_argument("--ics-url", help="Formula 1 ICS subscription URL.")
    parser.add_argument(
        "--workflow",
        default=str(BASE_DIR / ".github" / "workflows" / "f1-results.yml"),
        help="Workflow file containing the generated schedule markers.",
    )
    parser.add_argument("--year", type=int, default=dt.datetime.now(dt.timezone.utc).year)
    parser.add_argument("--retry-minutes", type=int, nargs="+", default=list(DEFAULT_RETRY_MINUTES))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    content = fetch_ics(args.ics_file, args.ics_url)
    events = [event for event in calendar_events_from_ics(content) if event.year == args.year]
    if not events:
        raise SystemExit(f"No F1 sessions found in the ICS calendar for {args.year}")

    retry_minutes = tuple(sorted(set(args.retry_minutes)))
    changed = update_workflow(Path(args.workflow), events, retry_minutes)
    entry_count = len(build_schedule_entries(events, retry_minutes))
    status = "updated" if changed else "unchanged"
    print(f"{status}: {entry_count} session trigger(s) for {len(events)} event(s) in {args.year}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
