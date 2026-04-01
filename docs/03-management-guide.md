# Time Tracking Management Guide

How the system should be used day-to-day, and how everything connects.

## Daily Workflow (current — manual)

### When starting work
1. Open TimeTagger and start a timer, or create an entry after the fact
2. Include a description that matches a Coda task (the sync will tag it)

### When logging time
- **Format:** `Description text #tsk-XXX #pro-XX #wo-XX #nsight`
- **Example:** `Fix camera FPS issue #tsk-220 #pro-47 #wo-14 #nsight`
- If you don't remember the task ID, log with just a description — you can tag it later in Coda
- The sync service runs every 60 seconds and will push new entries to Coda

### When finishing for the day
- Check that your hours are logged (the planned agent will remind you at 6pm)
- If you forgot to track, use the work log analyzer:
  ```bash
  cd tools/
  python3 work_log_analyzer.py YYYYMMDD
  ```
  This cross-references your activity log and screenshots to reconstruct what you worked on.

## Daily Workflow (planned — with AI agent)

### Morning (8:30am — agent-initiated)
Agent DMs you in Discord with:
- Hours logged this week so far
- Top tasks to focus on today
- Any unlogged days from the past week
- WO budget status

### During work
- Log time in TimeTagger as usual
- If you need to check status: ask the agent `/status` or `/status WO-14`
- After standups: paste the transcript and the agent extracts action items

### End of day (6pm — agent-initiated)
Agent DMs you:
- Hours logged today vs detected activity
- Offers to analyze and fill in gaps if needed
- You confirm or adjust

### Weekly (Friday 4pm — agent-initiated)
Agent DMs you with:
- Weekly hours breakdown by project
- WO budget comparison
- Tasks completed and still open
- Upcoming deadlines

## Tagging Rules

### Tag format
```
description #tsk-XXX #pro-XX #wo-XX #nsight
```

### Tag hierarchy
- `#tsk-XXX` — links to a specific task in Coda (required for proper rollup)
- `#pro-XX` — links to a project
- `#wo-XX` — links to a work order
- `#nsight` — client tag (always `#nsight` for nSight Surgical work)
- `#unassigned` — for work not yet on a work order

### Creating new tasks
When you start work that doesn't match an existing task:
1. Log time in TT with a descriptive name (no tags)
2. Later, create the task in Coda (or ask the agent to do it)
3. Tag the TT entry with the new task ID
4. The sync service propagates everything

### Editing tags
- **In TimeTagger:** Edit the description directly. Sync pushes to Coda within 60s.
- **In Coda:** Edit the `task_id`, `project_id`, `work_order_id`, or `client_tag` fields on the TimeTagger Data row. Sync pushes back to TT within 60s.
- **Conflict:** If both are edited between syncs, most recent edit wins.

## Work Order Structure

### Active Work Orders (as of March 2026)

**WO-13** (Jan 2026)
| Project | ID | Description | Tasks |
|---------|-----|-------------|-------|
| QA Bug Testing | PRO-40 | Platform QA testing | TSK-270, TSK-257, TSK-243 |
| De-id Service | PRO-41 | Wrap up de-identification | TSK-222, TSK-253, TSK-238, TSK-217 |
| Meetings/Admin | PRO-42 | Jan standups + meetings | TSK-260, TSK-242, TSK-244 |
| Quality Dashboard | PRO-43 | J&J Demo dashboard | TSK-247 |

**WO-14** (Feb-Mar 2026)
| Project | ID | Description | Tasks |
|---------|-----|-------------|-------|
| OR Live Updates | PRO-44 | OR Live feature work | TSK-213 through TSK-273 (28 tasks) |
| Recording Service | PRO-45 | Camera recorder replacement | TSK-225, TSK-231, TSK-236, etc. |
| Post-Processor | PRO-47 | Stability updates | TSK-216, TSK-221, TSK-223, etc. |
| Meetings/Admin | PRO-51 | Feb+ standups + meetings | TSK-261, TSK-258, TSK-227, TSK-219 |

**WO-15** (drafting)
| Project | ID | Description | Tasks |
|---------|-----|-------------|-------|
| Thor Documentation | PRO-50 | Deployment docs | TSK-214, TSK-215, TSK-224, TSK-254, TSK-246 |

### Unassigned work
- Camera research (6.1h) — needs a work order before it can be properly tagged

## Tools Reference

### work_log_analyzer.py
```bash
# Analyze a single day
python3 tools/work_log_analyzer.py 20260226

# Analyze a date range (weekdays only)
python3 tools/work_log_analyzer.py 20260101 20260228

# Analyze remaining unchecked days from checklist
python3 tools/work_log_analyzer.py --remaining

# Custom gap tolerance (default 15 min)
python3 tools/work_log_analyzer.py 20260226 --gap 10
```
Output: `reviews/analysis_YYYYMMDD.md` with work blocks, ambiguous activity, screenshot links, and existing TT entries.

### apply_tags.py
```bash
# Preview what would change
python3 tools/apply_tags.py --dry-run

# Apply tags (creates Coda tasks + updates TT entries)
python3 tools/apply_tags.py
```
Mapping from descriptions to projects is hardcoded in the script's `DESC_TO_PROJECT` dict.

### daily_review.sh
```bash
# Generate contact sheet (default 5-min interval)
./tools/daily_review.sh 20260320

# 10-minute interval
./tools/daily_review.sh 20260320 10

# Open after generating
./tools/daily_review.sh 20260320 10 --open
```
Output: `reviews/review_YYYYMMDD.jpg`

### sync_service.py
```bash
cd sync/

# One-shot sync (incremental)
python3 sync_service.py --once

# Full resync (ignores last-sync timestamp)
python3 sync_service.py --once --full

# Continuous (every 60s)
python3 sync_service.py

# Docker
docker compose up -d        # start
docker compose logs -f      # watch
docker compose down          # stop
```

## Coda Table Maintenance

### Columns to delete (pending)
These old N8N-era columns should be removed from the TimeTagger Data table in the Coda UI:
1. `updated_description`
2. `updated_task_tag`
3. `updated_project_tag`
4. `updated_work_order_tag`
5. `updated_client_tag`
6. `new_ds`
7. `updated_tags`
8. `Date Time (from epoc)`

### task_link formula
The `task_link` column in TimeTagger Data should use this formula to look up the matching task:
```
[All Tasks].Filter(thisRow.task_id.ToText().Upper().Substitute("#", "") = CurrentValue.[Task ID])
```
