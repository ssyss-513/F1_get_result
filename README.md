# F1 result Markdown generator

This folder contains a small automation that reads a Formula 1 `.ics` calendar,
waits until each session has ended, fetches the official Formula 1 results page,
and writes Markdown tables that can be pasted directly into the blog.
Driver cells keep both Chinese and English names, for example
`刘易斯·汉密尔顿 Lewis Hamilton`.

The generator writes Markdown files under `generated/<year>/<race>/`, records
processed sessions under `state/`, and can publish each completed session to the
blog through the signed HTTP publisher endpoint.

## Layout

```text
F1_get_result/
  f1_get_result.py          Main generator
  sync_workflow_schedule.py Convert ICS session times into exact Actions schedules
  publish_blog.py          Publish eligible sessions to one article per Grand Prix
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

GitHub's built-in `GITHUB_TOKEN` cannot push changes to workflow files. To let
the daily calendar sync commit schedule changes automatically, create a
fine-grained personal access token limited to this repository with **Contents:
Read and write** and **Workflows: Read and write**, then save it as the Actions
repository secret `WORKFLOW_PAT`. Without this secret, the sync reports pending
changes as a warning and exits successfully instead of failing every day.

## Automatic blog publishing

Deploy `f1-publish.php` and `app/f1_publish.php` from the blog project, then add
these repository secrets:

```text
BLOG_PUBLISH_URL=http://blog.jiwo.top/blog/f1-publish.php
BLOG_PUBLISH_SECRET=<the same signing secret configured on the blog>
```

The endpoint uses a timestamped HMAC signature, so the blog administrator
password is never sent by GitHub Actions. A Grand Prix has one stable article.
New sessions are added in calendar order, and publishing the same session again
replaces only that session. The existing 2026 Silverstone article is mapped to
`f1-2026-silver-stone` in `config/blog_publish.json`.

For a manual backfill in GitHub Actions, run **F1 result Markdown** with:

```text
year: 2026
race_slug: belgium
session: practice-1
force: true
```
