#!/usr/bin/env python3
"""Fetch work order, project, and time data for the LLM to interpret.

Usage:
    python3 get_status.py              # all work orders + TT hours summary
    python3 get_status.py WO-14        # specific work order + its projects/tasks
    python3 get_status.py --hours N    # TT hours for the last N days (default: 14)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bootstrap
bootstrap.init()

import data


def print_work_orders(wo_filter=None):
    """Print work order data."""
    work_orders = data.get_work_orders()

    if wo_filter:
        work_orders = [wo for wo in work_orders if wo.get("Work Order ID") == wo_filter]
        if not work_orders:
            print(f"No work order found: {wo_filter}", file=sys.stderr)
            sys.exit(1)
    else:
        # Default: skip archived WOs to keep output manageable
        work_orders = [wo for wo in work_orders if wo.get("Status") != "Archived"]

    print("## Work Orders\n")
    for wo in work_orders:
        wo_id = wo.get("Work Order ID", "?")
        print(f"### {wo_id}")
        for key, val in wo.items():
            if key == "row_id" or not val:
                continue
            # Deduplicate list values (Coda returns repeated entries)
            if isinstance(val, list):
                val = list(dict.fromkeys(val))
            print(f"- {key}: {val}")
        print()


def print_projects(wo_filter=None, active_wo_ids=None):
    """Print project data."""
    projects = data.get_projects()

    if wo_filter:
        projects = [p for p in projects if p.get("Work Order") == wo_filter]
    elif active_wo_ids is not None:
        projects = [p for p in projects if p.get("Work Order") in active_wo_ids]

    if not projects:
        return

    print("## Projects\n")
    for proj in projects:
        proj_id = proj.get("Project ID", "?")
        print(f"### {proj_id}")
        for key, val in proj.items():
            if key == "row_id" or not val:
                continue
            if isinstance(val, list):
                val = list(dict.fromkeys(val))
            print(f"- {key}: {val}")
        print()


def print_tasks(wo_filter=None):
    """Print task data."""
    tasks = data.get_tasks()

    if wo_filter:
        tasks = [t for t in tasks if t.get("work_order") == wo_filter]

    if not tasks:
        return

    print("## Tasks\n")
    for t in tasks:
        status = f" [{t.get('status')}]" if t.get("status") else ""
        print(f"- {t['task_id']} {t.get('name', '')}{status} (Project: {t.get('project', '?')})")
    print()


def print_hours(days=14, wo_filter=None):
    """Print TT hours aggregated by WO and project."""
    now = int(time.time())
    start = now - days * 86400
    records = data.get_tt_hours(start, now)

    if wo_filter:
        wo_tag = f"#{wo_filter.lower()}"
        records = [r for r in records if r["tags"]["work_order_id"] == wo_tag]

    if not records:
        print(f"## TimeTagger Hours (last {days} days)\n\nNo records found.\n")
        return

    total = round(sum(r["duration_hours"] for r in records), 2)
    by_wo = data.aggregate_hours(records, "work_order_id")
    by_project = data.aggregate_hours(records, "project_id")

    # Find untagged entries
    untagged = [r for r in records if not r["tags"]["work_order_id"]]

    print(f"## TimeTagger Hours (last {days} days)\n")
    print(f"Total: {total}h\n")

    print("By work order:")
    for tag, hours in sorted(by_wo.items(), key=lambda x: -x[1]):
        print(f"- {tag}: {hours}h")
    print()

    print("By project:")
    for tag, hours in sorted(by_project.items(), key=lambda x: -x[1]):
        print(f"- {tag}: {hours}h")
    print()

    if untagged:
        untagged_hours = round(sum(r["duration_hours"] for r in untagged), 2)
        print(f"Untagged entries: {len(untagged)} ({untagged_hours}h)")
        for r in untagged[:10]:
            print(f"  - {r['description']} ({r['duration_hours']}h)")
        print()


def main():
    wo_filter = None
    days = 14

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--hours" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i].upper().startswith("WO-"):
            wo_filter = args[i].upper()
            i += 1
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            sys.exit(1)

    try:
        # Get WO IDs for filtering projects in default view
        active_wo_ids = None
        if not wo_filter:
            wos = data.get_work_orders()
            active_wo_ids = {
                wo.get("Work Order ID") for wo in wos
                if wo.get("Status") != "Archived"
            }

        print_work_orders(wo_filter)
        print_projects(wo_filter, active_wo_ids)
        if wo_filter:
            print_tasks(wo_filter)
        print_hours(days, wo_filter)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
