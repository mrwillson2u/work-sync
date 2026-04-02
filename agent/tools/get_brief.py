#!/usr/bin/env python3
"""Fetch data for daily or weekly briefing.

Usage:
    python3 get_brief.py                # daily brief (current week context)
    python3 get_brief.py --weekly       # full week summary
    python3 get_brief.py --days N       # lookback N days for hours (default: 7)

Outputs raw data for the LLM to compose into a briefing:
- Hours logged per day this week
- Weekdays with no logged hours
- Hours by WO and project
- Untagged entries
- Open work orders with budget info
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


def get_week_bounds(today=None):
    """Get Monday 00:00 and Sunday 23:59 for the week containing today."""
    if today is None:
        today = datetime.now(TZ)
    monday = today - timedelta(days=today.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return monday, sunday


def print_daily_hours(records, week_start, today):
    """Print hours per day for the current week, flag missing weekdays."""
    by_day = data.aggregate_hours_by_day(records)

    print("## Hours by Day (this week)\n")
    day = week_start
    while day <= today:
        day_str = day.strftime("%Y-%m-%d")
        day_name = day.strftime("%A")
        hours = by_day.get(day_str, 0)
        is_weekday = day.weekday() < 5

        if hours > 0:
            print(f"- {day_name} {day_str}: {hours}h")
        elif is_weekday:
            print(f"- {day_name} {day_str}: 0h (no entries)")
        else:
            print(f"- {day_name} {day_str}: (weekend)")
        day += timedelta(days=1)

    total = sum(by_day.values())
    print(f"\nWeek total so far: {round(total, 2)}h")

    # List weekdays with no hours
    missing = []
    day = week_start
    while day <= today:
        if day.weekday() < 5:
            day_str = day.strftime("%Y-%m-%d")
            if by_day.get(day_str, 0) == 0:
                missing.append(f"{day.strftime('%A')} {day_str}")
        day += timedelta(days=1)

    if missing:
        print(f"\nWeekdays with no logged hours: {', '.join(missing)}")
    print()


def print_hours_breakdown(records):
    """Print hours aggregated by WO and project."""
    by_wo = data.aggregate_hours(records, "work_order_id")
    by_project = data.aggregate_hours(records, "project_id")

    print("## Hours by Work Order\n")
    for tag, hours in sorted(by_wo.items(), key=lambda x: -x[1]):
        print(f"- {tag}: {hours}h")

    print("\n## Hours by Project\n")
    for tag, hours in sorted(by_project.items(), key=lambda x: -x[1]):
        print(f"- {tag}: {hours}h")
    print()


def print_untagged(records):
    """Print untagged entries."""
    untagged = [r for r in records if not r["tags"]["work_order_id"]]
    if not untagged:
        return

    total = round(sum(r["duration_hours"] for r in untagged), 2)
    print(f"## Untagged Entries ({len(untagged)} entries, {total}h)\n")
    for r in untagged:
        print(f"- {r['description']} ({r['duration_hours']}h)")
    print()


def print_work_orders():
    """Print non-archived work orders with budget info."""
    work_orders = data.get_work_orders()
    active = [wo for wo in work_orders if wo.get("Status") not in ("Archived", None, "")]

    if not active:
        return

    print("## Active Work Orders\n")
    for wo in active:
        wo_id = wo.get("Work Order ID", "?")
        status = wo.get("Status", "?")
        est = wo.get("Estimated Hours", 0)
        contingency = wo.get("Contingency", 0)
        logged = wo.get("Hours Logged", 0)
        end = wo.get("Expected End", "")

        print(f"### {wo_id} — {status}")
        if est:
            print(f"- Estimated: {est}h + {contingency}h contingency")
        if logged:
            print(f"- Coda Hours Logged: {logged}")
        if end:
            print(f"- Expected End: {end[:10]}")
        projects = wo.get("Projects", [])
        if projects:
            if isinstance(projects, list):
                projects = list(dict.fromkeys(projects))
            print(f"- Projects: {projects}")
        print()


def main():
    weekly = False
    days = 7

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--weekly":
            weekly = True
            i += 1
        elif args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            sys.exit(1)

    try:
        now = datetime.now(TZ)
        week_start, week_end = get_week_bounds(now)

        if weekly:
            # Full week: Mon-Sun
            start_epoch = int(week_start.timestamp())
            end_epoch = int(week_end.timestamp())
            print(f"# Weekly Summary ({week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')})\n")
        else:
            # Daily brief: show the current week up to now
            start_epoch = int(week_start.timestamp())
            end_epoch = int(now.timestamp())
            print(f"# Daily Brief — {now.strftime('%A %Y-%m-%d')}\n")

        records = data.get_tt_hours(start_epoch, end_epoch)

        print_daily_hours(records, week_start, now)
        print_hours_breakdown(records)
        print_untagged(records)
        print_work_orders()

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
