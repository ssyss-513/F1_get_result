import datetime as dt
import tempfile
import unittest
from pathlib import Path

from f1_get_result import CalendarEvent
from sync_workflow_schedule import build_schedule_entries, update_workflow


def event(end: dt.datetime, session_key: str = "practice-2") -> CalendarEvent:
    return CalendarEvent(
        uid=f"test-{session_key}",
        summary=f"Belgian Grand Prix - {session_key}",
        location="Belgium",
        start=end - dt.timedelta(hours=1),
        end=end,
        year=end.year,
        race_title="Belgian Grand Prix",
        session_key=session_key,
    )


class ScheduleEntriesTest(unittest.TestCase):
    def test_builds_retries_from_session_end(self) -> None:
        entries = build_schedule_entries(
            [event(dt.datetime(2026, 7, 17, 16, 0, tzinfo=dt.timezone.utc))],
            retry_minutes=(17, 47),
        )

        self.assertEqual(
            entries,
            [
                ("17 16 17 7 *", "2026-07-17 practice-2 +17m"),
                ("47 16 17 7 *", "2026-07-17 practice-2 +47m"),
            ],
        )

    def test_rolls_retry_into_next_utc_day(self) -> None:
        entries = build_schedule_entries(
            [event(dt.datetime(2026, 7, 17, 23, 50, tzinfo=dt.timezone.utc))],
            retry_minutes=(17,),
        )

        self.assertEqual(entries, [("7 0 18 7 *", "2026-07-17 practice-2 +17m")])

    def test_updates_only_generated_workflow_block(self) -> None:
        workflow = """name: Test
on:
  schedule:
    # BEGIN GENERATED F1 SESSION SCHEDULE
    - cron: \"23,53 * * * *\"
    # END GENERATED F1 SESSION SCHEDULE
  workflow_dispatch:
jobs: {}
"""
        calendar_event = event(dt.datetime(2026, 7, 17, 16, 0, tzinfo=dt.timezone.utc))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.yml"
            path.write_text(workflow, encoding="utf-8")
            changed = update_workflow(path, [calendar_event], retry_minutes=(17, 47))
            updated = path.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertIn('- cron: "17 4 * * *" # daily recovery', updated)
        self.assertIn('- cron: "17 16 17 7 *" # 2026-07-17 practice-2 +17m', updated)
        self.assertIn('- cron: "47 16 17 7 *" # 2026-07-17 practice-2 +47m', updated)
        self.assertIn("workflow_dispatch:", updated)
        self.assertNotIn("23,53", updated)


if __name__ == "__main__":
    unittest.main()
