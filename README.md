# F1 result Markdown generator

This folder contains a small automation that reads a Formula 1 `.ics` calendar,
waits until each session has ended, fetches the official Formula 1 results page,
and writes Markdown tables that can be pasted directly into the blog.
Driver cells keep both Chinese and English names, for example
`刘易斯·汉密尔顿 Lewis Hamilton`.

The generator does not publish to the blog database. It only writes Markdown
files under `generated/<year>/<race>/` and records processed sessions under
`state/`.

## Layout

```text
F1_get_result/
  f1_get_result.py          Main generator
  sync_workflow_schedule.py Convert ICS session times into exact Actions schedules
  config/translations.json  Chinese driver/team/session names
  config/race_aliases.json  Calendar location/title to F1 result slug hints
  data/                     Optional checked-in ICS file location
  generated/                Generated Markdown files
  state/                    De-duplication state
```

## Local usage

List sessions parsed from your ICS file:

```bash
python3 f1_get_result.py \
  --ics-file /Users/shiyusen/Downloads/Formula_1.ics \
  --list-events
```

Generate results for sessions that ended recently:

```bash
python3 f1_get_result.py \
  --ics-file /Users/shiyusen/Downloads/Formula_1.ics \
  --lookback-hours 96 \
  --delay-minutes 20
```

Force a specific session, useful for backfilling:

```bash
python3 f1_get_result.py \
  --ics-file /Users/shiyusen/Downloads/Formula_1.ics \
  --year 2026 \
  --race-slug great-britain \
  --session qualifying \
  --force
```

## GitHub Actions setup

The workflow is installed at:

```text
.github/workflows/f1-results.yml
```

The result workflow is generated from the ICS calendar. For every session it
runs 17 minutes after the calendar end time, retries 30 minutes later, and has
one daily recovery run. It commits new files under:

```text
generated/
state/
```

For a private calendar URL, add a GitHub repository secret named:

```text
F1_ICS_URL
```

If you do not want to use a secret, commit the calendar file as:

```text
data/Formula_1.ics
```

Do not commit a private subscription URL into the repository.

The **Sync F1 calendar schedule** workflow runs daily. It reads the same ICS
source and updates the exact UTC triggers in `f1-results.yml` when the calendar
changes. To regenerate them locally:

```bash
python3 sync_workflow_schedule.py \
  --ics-file /Users/shiyusen/Downloads/Formula_1.ics \
  --year 2026
```

For a manual backfill in GitHub Actions, run **F1 result Markdown** with:

```text
year: 2026
race_slug: belgium
session: practice-1
force: true
```
