# AI Agent Plan — OpenClaw Work Tracker

## Overview

An AI agent running on OpenClaw that acts as a friendly project manager, helping Colin stay on track with time logging, task management, and invoicing. Operates entirely through Discord.

## Agent Identity

The agent is a **friendly project manager** — not a tool, but a teammate:

- **Knows the full picture** — work orders, budgets, deadlines, standup context
- **Proactively checks in** — doesn't wait to be asked
- **Reduces cognitive load** — makes recommendations, pre-fills details, handles busywork
- **Patient and non-judgmental** — ADHD means some days are harder. Adapts, doesn't nag.
- **Gently accountable** — "I noticed you haven't logged time today. Want me to check your activity?" not "You forgot again."
- **Learns over time** — remembers patterns, preferences, working style

## Architecture

```
Colin's existing OpenClaw agent (Discord)
├── General assistant (default behavior)
├── Work Tracker skill (SKILL.md + tools)
│   ├── Cron jobs: morning brief, log reminder, weekly review, audit
│   └── On-demand: status, invoice, newwork, standup review
└── Other skills (future)
```

**Single agent, not separate.** Work tracker is a skill on Colin's existing general-purpose OpenClaw agent. This gives holistic context (work + life) for better recommendations. Can split later if needed.

**Model-agnostic.** OpenClaw supports multiple LLM providers. Claude is preferred but can swap to cheaper models if budget is tight.

## Workflows

### Scheduled (cron jobs — run in isolated sessions)

#### 1. Morning Brief — weekdays 8:30am
**Purpose:** Remove "what should I work on?" decision paralysis.

DMs Colin with:
- Hours logged this week so far vs target
- Top 3 tasks to focus on (from Coda active tasks, by priority/deadline)
- Any unlogged days from the past week
- WO budget status (hours used vs allotted per project)

**OpenClaw config:**
```bash
openclaw cron add \
  --name "Morning Brief" \
  --cron "30 8 * * 1-5" \
  --tz "America/Los_Angeles" \
  --session isolated \
  --message "Run the morning brief workflow" \
  --announce --channel discord --to "channel:CHANNEL_ID"
```

**Tools needed:** `get_brief.py` → calls Coda + TT APIs, returns formatted summary

#### 2. Log Reminder — weekdays 6pm
**Purpose:** Catch unlogged time same-day instead of months later.

DMs Colin with:
- Hours logged today vs detected screenshot/activity
- If significant gap: "Looks like you worked from 9am-5pm but only logged 3 hours. Want me to analyze?"
- If Colin says yes → runs work_log_analyzer, suggests entries, pushes to TT with confirmation

**Tools needed:** `check_logs.py` → queries TT for today's entries, checks activity_log.db for work activity, compares

#### 3. Weekly Review — Friday 4pm
**Purpose:** Prevent "I'll do the review later" procrastination.

DMs Colin with:
- Hours breakdown by project this week
- WO budget comparison (on track? over?)
- Tasks completed and still open
- Upcoming deadlines
- "Anything to add or correct before the week closes?"

**Tools needed:** `get_brief.py --weekly` → same data layer, aggregated

#### 4. System Audit — weekly (background)
**Purpose:** System maintains itself; Colin only hears about problems.

Runs silently. Only alerts if:
- Sync service has errors
- Untagged TT entries exist
- Coda/TT data mismatches
- Tasks without estimates
- WO hours approaching limits (>80%)
- Stale tasks (in progress, no TT activity for 2+ weeks)

**Tools needed:** `run_audit.py` → checks all systems, returns issues or "all clear"

### On-Demand (conversational — in Discord)

#### 5. Status Check
**Trigger:** Colin asks "what's my status?" or "how's WO-14 looking?"

Returns:
- Hours per project/WO (used vs budget)
- Active tasks and their status
- Flagged issues

**Tools needed:** `get_status.py [WO-14]` → Coda + TT query

#### 6. Invoice Helper
**Trigger:** Colin asks "help me invoice WO-14" or "what are my March hours?"

Agent:
- Pulls all tagged TT entries for the period/WO
- Groups by project, calculates totals
- Compares to WO budget
- Generates summary in Colin's template format
- Flags issues (over budget, untagged time)

**Tools needed:** `generate_invoice.py --wo WO-14 --period 2026-03` → data aggregation

#### 7. New Work Setup (conversational)
**Trigger:** Colin says "I need to set up a new work order"

Agent walks through conversationally:
1. **Work Order:** Client, scope, dates → creates WO-XX in Coda
2. **Projects:** "What are the separate lanes of work?" → creates PRO-XX entries. Each project is a distinct area of work (not a phase).
3. **Tasks:** For each project, suggests task breakdown. Colin accepts/modifies. Creates TSK-XXX entries with TT description templates.
4. **Review:** Shows full structure, hour estimates, timeline. Colin confirms.
5. **Future:** Generate Google Doc work order template (once Colin provides the template)

Agent suggests start dates, asks for priorities, helps fill in details/descriptions based on past WOs.

**Tools needed:** `create_work.py` → Coda API write operations (create WO, project, tasks)

#### 8. Standup Transcript Review
**Trigger:** Colin pastes a transcript or says "review today's standup"

Agent:
- Parses transcript for action items and mentions of Colin's work
- Extracts tasks: "Colin to fix camera FPS by Friday" → suggests creating/updating a task
- Cross-references with Coda tasks — links existing or flags new work
- Updates task statuses if discussed
- Stores key decisions in memory for ongoing context

**Tools needed:** `review_standup.py` → optional preprocessing, but mostly LLM reasoning over transcript + Coda data

## Tool Architecture

Tools are **Python CLI scripts** that the OpenClaw agent calls via the `exec` tool. Each script:
- Reads credentials from environment variables (same `.env` as sync service)
- Reuses `sync/tt_client.py` and `sync/coda_client.py` for API access
- Outputs structured text that the LLM can reason about
- Is independently testable: `python3 get_status.py WO-14`

```
agent/
├── tools/
│   ├── get_status.py
│   ├── get_brief.py
│   ├── check_logs.py
│   ├── create_work.py
│   ├── generate_invoice.py
│   ├── review_standup.py
│   └── run_audit.py
├── data.py                  # Shared data fetching layer
└── README.md                # OpenClaw setup instructions
```

Tools documented in the OpenClaw workspace `TOOLS.md` so the agent knows how to call them.

## OpenClaw Workspace Files

These files configure the agent's behavior:

| File | Purpose |
|------|---------|
| `AGENTS.md` | Operating instructions, workflow definitions |
| `SOUL.md` | PM persona, tone, ADHD-awareness guidelines |
| `USER.md` | Colin's identity, role, work patterns |
| `TOOLS.md` | How to call each Python tool (paths, arguments, output format) |
| `HEARTBEAT.md` | Periodic checklist (check sync health, pending items) |
| `MEMORY.md` | Long-term facts (WO budgets, preferences, standup context) |
| `skills/work-tracker/SKILL.md` | Work tracker skill definition |

## Implementation Order

| # | Step | Description | Depends on |
|---|------|-------------|------------|
| 1 | Data layer | `agent/data.py` — shared Coda/TT query functions | sync/ clients |
| 2 | Status tool | `get_status.py` — simplest useful tool, proves pipeline | data layer |
| 3 | Workspace files | AGENTS.md, SOUL.md, USER.md, TOOLS.md | status tool |
| 4 | Morning brief | `get_brief.py` + cron job — first scheduled workflow | data layer |
| 5 | Log reminder | `check_logs.py` — uses work_log_analyzer, biggest daily value | data layer |
| 6 | New work setup | `create_work.py` — most complex conversational flow | data layer |
| 7 | Invoice helper | `generate_invoice.py` — data aggregation | data layer |
| 8 | Weekly review | Extension of morning brief | brief tool |
| 9 | Standup review | `review_standup.py` — transcript parsing | data layer |
| 10 | System audit | `run_audit.py` — background health check | everything |

## Next Steps (for next session)

1. **SSH into the OpenClaw Raspberry Pi** to understand the current workspace structure
2. **Build `agent/data.py`** — shared data fetching that reuses sync/ API clients
3. **Build `get_status.py`** — first tool, test it works via `exec`
4. **Write workspace files** — SOUL.md (PM persona), TOOLS.md (tool docs), SKILL.md
5. **Configure first cron job** — morning brief as proof of concept
6. **Iterate** — add remaining workflows one at a time

## Open Questions

- What is the current OpenClaw workspace structure on the Pi?
- What Discord channel/server IDs to use for notifications?
- Does Colin want separate Discord channels for different notification types?
- Google Doc invoice template — Colin will provide when ready
- How does the standup transcript get captured? (Loom? Manual paste? Auto-transcription?)
