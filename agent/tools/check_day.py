#!/usr/bin/env python3
"""Fetch today's work data for an end-of-day check-in conversation.

Usage:
    python3 check_day.py              # today's data
    python3 check_day.py 2026-03-31   # specific date

Outputs:
- What was logged in TimeTagger today (entries with times and descriptions)
- Active tasks from Coda (for comparing plan vs actual)
- Today's total hours
"""

import os
import sys
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


def main():
    # Parse date argument
    if len(sys.argv) > 1:
        try:
            target = datetime.strptime(sys.argv[1], "%Y-%m-%d")
            target = target.replace(tzinfo=TZ)
        except ValueError:
            print(f"Invalid date format: {sys.argv[1]} (expected YYYY-MM-DD)", file=sys.stderr)
            sys.exit(1)
    else:
        target = datetime.now(TZ)

    day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    try:
        records = data.get_tt_hours(int(day_start.timestamp()), int(day_end.timestamp()))

        print(f"# End of Day — {target.strftime('%A %Y-%m-%d')}\n")

        # Today's entries with times
        if records:
            total = round(sum(r["duration_hours"] for r in records), 2)
            print(f"## Time Logged Today: {total}h\n")

            # Sort by start time
            records.sort(key=lambda r: r["t1"])
            for r in records:
                start = datetime.fromtimestamp(r["t1"], tz=TZ).strftime("%I:%M%p")
                end = datetime.fromtimestamp(r["t2"], tz=TZ).strftime("%I:%M%p")
                tags = r["tags"]
                tag_str = ""
                if tags["work_order_id"]:
                    tag_str = f" [{tags['work_order_id']}"
                    if tags["project_id"]:
                        tag_str += f" {tags['project_id']}"
                    tag_str += "]"
                elif not tags["work_order_id"]:
                    tag_str = " [untagged]"

                print(f"- {start}-{end}: {r['description']} ({r['duration_hours']}h){tag_str}")
            print()
        else:
            print("## Time Logged Today: 0h\n")
            print("No TimeTagger entries found for this day.\n")

        # Active tasks — only from non-archived/paid WOs
        work_orders = data.get_work_orders()
        active_wos = {
            wo.get("Work Order ID") for wo in work_orders
            if wo.get("Status") in ("Open", "Drafting")
        }
        tasks = data.get_tasks()
        active = [t for t in tasks if t.get("work_order") in active_wos]

        if active:
            print(f"## Active Tasks ({len(active)})\n")
            # Group by WO
            by_wo = {}
            for t in active:
                wo = t.get("work_order", "Unknown")
                by_wo.setdefault(wo, []).append(t)

            for wo, wo_tasks in sorted(by_wo.items()):
                print(f"### {wo}")
                for t in wo_tasks:
                    print(f"- {t['task_id']} {t.get('name', '')} ({t.get('project', '?')})")
                print()

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
