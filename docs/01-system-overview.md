# Work Tracking System — Architecture Overview

## Purpose

Colin is a contractor for nSight Surgical. His employer requires approved work orders with task-level time estimates, and invoices cannot exceed approved hours per project. This system tracks time, organizes tasks, syncs data, and will eventually be managed by an AI assistant.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        DATA LAYER                           │
│                                                             │
│  ┌──────────────┐    sync/sync_service.py    ┌──────────┐  │
│  │  TimeTagger   │◄────── every 60s ────────►│   Coda   │  │
│  │  (time logs)  │                            │  (tasks) │  │
│  └──────────────┘                            └──────────┘  │
│         │                                          │        │
│         │  Source of truth                  Task mgmt       │
│         │  for time entries                WO/project       │
│         │                                  structure        │
│                                                             │
│  ┌──────────────┐                                           │
│  │ Activity Log  │  time-monitor/activity_log.db            │
│  │ (5s interval) │  + screenshots every 60s                 │
│  └──────────────┘                                           │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                        TOOL LAYER                           │
│                                                             │
│  tools/work_log_analyzer.py  — Reconstruct work from logs   │
│  tools/apply_tags.py         — Bulk create tasks + tag TT   │
│  tools/daily_review.sh       — Screenshot contact sheets    │
│  tools/activity_classifier.json — Work/personal rules       │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                     AI AGENT LAYER (planned)                │
│                                                             │
│  OpenClaw agent → Discord                                   │
│  Scheduled: morning brief, log reminder, weekly review      │
│  On-demand: /status, /invoice, /newwork, standup review     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Services

### TimeTagger (time tracking)
- **What:** Self-hosted open-source time tracker
- **URL:** `timetagger.botnique.com/timetagger/`
- **Access:** JWT auth token + Cloudflare Zero Trust (CF-Access-Client-Id/Secret)
- **API quirk:** Requires `User-Agent` header or Cloudflare returns 1010 error
- **Key endpoints:**
  - `GET /api/v2/records?timerange=START-END` — fetch records
  - `GET /api/v2/updates?since=EPOCH` — incremental sync
  - `PUT /api/v2/records` — upsert (accepts JSON array, not wrapped object)
- **Tagging format:** Description field contains `description text #tsk-XXX #pro-XX #wo-XX #nsight`

### Coda (task/project management)
- **What:** Document-based project tracker
- **Doc ID:** `OSAZiA68PX`
- **Key tables:**
  - `All Tasks` (grid-L6CM1HyWMk) — 244 tasks with Task ID, Project, WO, Client, Hours
  - `TimeTagger Data` (grid-9FUJAxlzM1) — Mirror of TT records with parsed tags
  - `Projects` (grid-Xvp3xIJw15) — PRO-XX entries
  - `Work Orders` (grid-0Xxvqy_u70) — WO-XX entries
  - `Clients` (grid-sChOaO0Qdi) — nSight Surgical, Personal, Stinson
- **API:** REST at `coda.io/apis/v1`. Rate limit ~10 req/sec, need 2-3s delay between writes.
- **Formula columns (read-only):** `ds_clean`, `minutes` — cannot be written via API

### Activity Monitor (time-monitor repo)
- **What:** Python daemon logging active window every 5 seconds + screenshot every 60 seconds
- **DB:** `time-monitor/activity_log.db` (SQLite, ~1.2M records since June 2025)
- **Screenshots:** `time-monitor/screenshots/YYYYMMDD/YYYYMMDD_HHMMSS.png`
- **Quirk:** Window titles sometimes show a different app than `app_name` (captures status bar). The work_log_analyzer handles this.

### Sync Service
- **What:** Python service that keeps TimeTagger and Coda in bi-directional sync
- **Location:** `sync/` directory
- **Runs:** Every 60 seconds in Docker on Colin's homeserver
- **Phases:**
  1. TT → Coda: Upsert new/modified records. Skips tag fields if Coda has a pending human edit.
  2. Coda → TT: Push tag edits from Coda back to TT descriptions. Only processes rows edited since last sync.
  3. Task reassignments: Propagate project/WO changes from All Tasks to linked TT Data rows.
- **Conflict resolution:** Most recent edit wins (TT `mt` vs Coda `updatedAt`)
- **State:** Persisted in `/data/sync_state.json` (Docker volume)

## Data Hierarchy

```
Client (nSight Surgical)
└── Work Order (WO-14)
    ├── Project (PRO-44: OR Live Updates)
    │   ├── Task (TSK-265: Test updated code)
    │   │   └── TimeTagger entries tagged #tsk-265 #pro-44 #wo-14 #nsight
    │   └── Task (TSK-252: OR live user authentication)
    │       └── TimeTagger entries tagged #tsk-252 #pro-44 #wo-14 #nsight
    ├── Project (PRO-45: Recording Service)
    │   └── ...
    └── Project (PRO-51: Meetings/Admin)
        └── Task (TSK-261: Standup)
```

## Credentials

All stored in `/Users/colinwillson/Repositories/work-tracker/.env`:
- `CODA_API_TOKEN`
- `TIMETAGGER_URL`, `TIMETAGGER_API_TOKEN`
- `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`
- `N8N_URL`, `N8N_API_KEY` (deprecated — N8N replaced by sync service)

## File Structure

```
work-tracker/
├── .env                          # Credentials (not committed)
├── .gitignore
├── sync/                         # Bi-directional sync service
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── sync_service.py           # Main sync loop (3 phases)
│   ├── tt_client.py              # TimeTagger API wrapper
│   ├── coda_client.py            # Coda API wrapper
│   ├── config.py                 # Constants, column IDs, tag parsing
│   └── requirements.txt
├── tools/                        # Standalone analysis/management tools
│   ├── work_log_analyzer.py      # Cross-reference activity + screenshots + TT
│   ├── apply_tags.py             # Bulk create Coda tasks + tag TT entries
│   ├── daily_review.sh           # Generate screenshot contact sheet JPEGs
│   └── activity_classifier.json  # Work/personal classification rules
├── audit/                        # Data exports and audit reports (not committed)
│   ├── tagging_plan.md
│   ├── tagging_worksheet_v2.md
│   ├── AUDIT_REPORT.md
│   └── *.json                    # Coda/TT data exports
├── reviews/                      # Generated analysis reports (not committed)
│   ├── analysis_YYYYMMDD.md
│   ├── review_YYYYMMDD.jpg
│   └── unlogged_days_checklist.md
└── docs/                         # This documentation
```
