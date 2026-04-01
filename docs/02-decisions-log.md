# Decisions Log

Chronological record of key decisions made during the system build, with rationale.

## 2026-03-30 — Backfill approach

**Decision:** Use activity_log.db (5-second window tracking) as primary source for reconstructing work history, cross-referenced with screenshots and existing TT entries.

**Why:** Screenshots only capture 1 of 3 monitors. The activity DB captures the focused window regardless of which monitor it's on. Together they give a much more complete picture than screenshots alone.

**Result:** Built `tools/work_log_analyzer.py` with configurable classifier (`activity_classifier.json`).

## 2026-03-30 — Activity classification rules

**Decision:** Personal-first checking order for Chrome window titles. Key classifications:

- **Work:** nsight*, orlive*, colin@nsightsurgical.ai, github, linear, jira, coda, grafana, staging/production
- **Personal:** cloudflare, botnique, n8n, timetagger, youtube, shopping, reddit, colinwillson@gmail.com, slack
- **Personal apps:** Steam, Discord, Messages, Telegram, Monodraw, Fusion, inav-configurator, Simplify3D, Firefox, Slack, Notes, NAPS2, Seafile/SeaDrive
- **Work apps:** VLC, Loom, Microsoft Teams, Box
- **Ambiguous:** ChatGPT/Claude/OpenAI, localhost, docker, Code (without work keywords)

**Why:** Colin's personal infrastructure (cloudflare, botnique, n8n, timetagger) was initially classified as work. Corrected after Colin flagged it. Personal keywords checked before work keywords in Chrome to prevent false positives.

## 2026-03-30 — Work block merge tolerance

**Decision:** 15-minute gap tolerance for merging adjacent work blocks.

**Why:** Started at 5 minutes, then increased. Work sessions often have brief interruptions (checking email, getting coffee) that shouldn't split a continuous block. 15 minutes matches how Colin naturally logs time.

## 2026-03-31 — Tagging: one Coda task per unique TT description

**Decision:** Create a new Coda task for every unique TimeTagger description, rather than mapping descriptions to existing tasks.

**Why:** Simpler — no ambiguous mapping decisions. Each description gets its own TSK-XXX. Created TSK-213 through TSK-275 (63 tasks).

## 2026-03-31 — Standup date split

**Decision:** Standups before Feb 2 2026 → PRO-42/WO-13, Feb 2 onward → PRO-51/WO-14.

**Why:** WO-14 starts Feb 2. Standups need to be tracked against the correct work order for invoicing. Created new PRO-51 (Meetings/Admin) under WO-14 since no meetings project existed there.

## 2026-03-31 — Sync service: Python replacing N8N

**Decision:** Replace N8N workflows with a Python sync service running in Docker.

**Why:**
- N8N had edge case bugs and disabled nodes that caused silent failures
- Visual workflow editor made version control awkward
- Lock mechanism added complexity
- Python is version-controlled, debuggable, and readable by the planned AI assistant
- Removes dependency on N8N server
- Docker makes it portable (Mac now, Linux homeserver later)

## 2026-03-31 — Sync direction: bi-directional

**Decision:** Bi-directional sync (TT↔Coda) with most-recent-edit-wins conflict resolution.

**Why:** Colin edits in both places. Tags sometimes need correction in Coda (bulk operations), time entries get adjusted in TT directly.

## 2026-03-31 — Coda table restructure: remove dual tag fields

**Decision:** Remove 8 redundant columns from TimeTagger Data table (updated_description, updated_task_tag, updated_project_tag, updated_work_order_tag, updated_client_tag, new_ds, updated_tags, Date Time from epoc).

**Why:** The dual tag fields (current vs updated) were the source of N8N bugs. Having two sources of truth for the same data in one row created phantom diffs and confusion. Simplified to single set of tag fields. Pending Coda edits detected by comparing tag fields against ds content.

**Status:** Columns need to be manually deleted from Coda UI (API doesn't support column deletion).

## 2026-03-31 — AI agent: OpenClaw with single agent

**Decision:** Use OpenClaw as the AI agent platform, with a single general-purpose agent that has work tracking as a skill (not a separate dedicated agent).

**Why:**
- OpenClaw is model-agnostic (can swap Claude for cheaper models if needed)
- Has built-in scheduling (cron + heartbeat) and Discord integration
- Single agent gives holistic life context (can help with work/life balance, not just work tracking)
- Less ADHD friction (no deciding which bot to message)
- Can split into separate agents later if context bleed becomes a problem

## 2026-03-31 — Agent identity: friendly project manager

**Decision:** The agent's persona is a friendly PM whose goal is to help Colin be successful. Not a tool, but a teammate.

**Why:** Colin has ADHD. The agent needs to be proactive (come to him), reduce cognitive load (make recommendations), and be non-judgmental (adapt to hard days). A PM framing captures all of this better than "assistant" or "bot."

## 2026-03-31 — Projects are parallel lanes, not phases

**Decision:** Projects under a work order represent distinct parallel areas of work (e.g., OR Live, Recording Service), not sequential phases (Research → Implementation → Testing).

**Why:** Colin clarified that tasks like research, implementation, and testing for a single area belong under one project. Separate projects are for separate lanes of work.
