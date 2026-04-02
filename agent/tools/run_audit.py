#!/usr/bin/env python3
"""System health check — fetch data for the LLM to audit.

Usage:
    python3 run_audit.py

Outputs raw data about potential issues for the LLM to evaluate:
- Untagged TT entries (no WO tag)
- TT entries with partial tags (has project but no WO, or vice versa)
- Weekdays with no logged hours in the past 2 weeks
- Work order budget vs actual hours comparison
- Tasks without time entries
"""

import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bootstrap
bootstrap.init()

import data

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Los_Angeles")
except ImportError:
    from datetime import timezone
    TZ = timezone(timedelta(hours=-7))


def print_untagged_entries(records):
    """Print entries missing WO or project tags."""
    no_wo = [r for r in records if not r["tags"]["work_order_id"]]
    partial = [
        r for r in records
        if (r["tags"]["work_order_id"] and not r["tags"]["project_id"])
        or (r["tags"]["project_id"] and not r["tags"]["work_order_id"])
    ]

    if no_wo:
        total = round(sum(r["duration_hours"] for r in no_wo), 2)
        print(f"## Untagged Entries ({len(no_wo)} entries, {total}h)\n")
        for r in no_wo:
            print(f"- {r['description']} ({r['duration_hours']}h)")
        print()

    if partial:
        total = round(sum(r["duration_hours"] for r in partial), 2)
        print(f"## Partially Tagged Entries ({len(partial)} entries, {total}h)\n")
        for r in partial:
            tags = r["tags"]
            print(f"- {r['description']} ({r['duration_hours']}h) — WO: {tags['work_order_id'] or 'missing'}, Project: {tags['project_id'] or 'missing'}")
        print()

    if not no_wo and not partial:
        print("## Tagging: All entries fully tagged\n")


def print_missing_days(records, lookback_days=14):
    """Print weekdays with no logged hours."""
    by_day = data.aggregate_hours_by_day(records)
    today = datetime.now(TZ).date()

    missing = []
    for i in range(lookback_days):
        day = today - timedelta(days=i)
        if day.weekday() < 5:  # weekday
            day_str = day.strftime("%Y-%m-%d")
            hours = by_day.get(day_str, 0)
            if hours == 0:
                missing.append(f"{day.strftime('%A')} {day_str}")

    if missing:
        print(f"## Weekdays With No Logged Hours (past {lookback_days} days)\n")
        for d in missing:
            print(f"- {d}")
        print()
    else:
        print(f"## Logged Hours: All weekdays covered (past {lookback_days} days)\n")


def print_budget_comparison(records):
    """Print WO budget vs actual TT hours for non-archived WOs."""
    work_orders = data.get_work_orders()
    active = [wo for wo in work_orders if wo.get("Status") not in ("Archived", None, "")]

    by_wo = data.aggregate_hours(records, "work_order_id")

    print("## Work Order Budget vs Actual (from TimeTagger)\n")
    print("| WO | Status | Estimated | Contingency | TT Hours | Coda Hours |")
    print("|----|--------|-----------|-------------|----------|------------|")
    for wo in active:
        wo_id = wo.get("Work Order ID", "?")
        wo_tag = f"#{wo_id.lower()}"
        tt_hours = by_wo.get(wo_tag, 0)
        print(
            f"| {wo_id}"
            f" | {wo.get('Status', '?')}"
            f" | {wo.get('Estimated Hours', 0)}"
            f" | {wo.get('Contingency', 0)}"
            f" | {tt_hours}"
            f" | {round(wo.get('Hours Logged', 0), 2)}"
            f" |"
        )
    print()


def print_tasks_without_hours(records, tasks):
    """Print tasks that exist in Coda but have no TT time entries."""
    # Get all task tags that appear in TT records
    tasks_with_time = set()
    for r in records:
        tid = r["tags"].get("task_id")
        if tid:
            tasks_with_time.add(tid.lower())

    # Filter to tasks in non-archived WOs
    no_time = [
        t for t in tasks
        if f"#{t['task_id'].lower()}" not in tasks_with_time
        and t.get("work_order")
    ]

    if no_time:
        print(f"## Tasks With No Time Entries ({len(no_time)})\n")
        for t in no_time[:30]:  # cap at 30 to avoid huge output
            print(f"- {t['task_id']} {t.get('name', '')} (WO: {t.get('work_order', '?')})")
        if len(no_time) > 30:
            print(f"- ... and {len(no_time) - 30} more")
        print()
    else:
        print("## Tasks: All tasks have time entries\n")


def main():
    try:
        now = int(time.time())
        # Fetch TT records for a wide range (6 months back)
        start = now - 180 * 86400
        records = data.get_tt_hours(start, now)
        tasks = data.get_tasks()

        # Recent records for tagging/missing day checks
        recent_start = now - 14 * 86400
        recent_records = [r for r in records if r["t1"] >= recent_start]

        print("# System Audit\n")

        print_untagged_entries(recent_records)
        print_missing_days(recent_records)
        print_budget_comparison(records)
        print_tasks_without_hours(records, tasks)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
