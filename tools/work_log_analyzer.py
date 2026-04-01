#!/usr/bin/env python3
"""
Work Log Analyzer — cross-references activity logs, screenshots, and TimeTagger
to produce actionable daily work summaries for backfilling time entries.

Usage:
    python work_log_analyzer.py 20260226              # single day
    python work_log_analyzer.py 20260226 20260228     # date range
    python work_log_analyzer.py --remaining           # unchecked days from checklist
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
CLASSIFIER_PATH = os.path.join(SCRIPT_DIR, "activity_classifier.json")
DB_PATH = "/Users/colinwillson/Repositories/time-monitor/activity_log.db"
SCREENSHOTS_DIR = "/Users/colinwillson/Repositories/time-monitor/screenshots"
OUTPUT_DIR = os.path.join(REPO_DIR, "reviews")
CHECKLIST_PATH = os.path.join(OUTPUT_DIR, "unlogged_days_checklist.md")
ENV_PATH = os.path.join(REPO_DIR, ".env")

GAP_TOLERANCE_MIN = 15  # merge work blocks separated by less than this


def load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def load_classifier():
    with open(CLASSIFIER_PATH) as f:
        return json.load(f)


def get_activity_entries(date_str):
    """Query activity_log.db for entries on the given date (YYYYMMDD), 07:00-22:00."""
    d = datetime.strptime(date_str, "%Y%m%d").date()
    start = datetime(d.year, d.month, d.day, 7, 0, 0).isoformat()
    end = datetime(d.year, d.month, d.day, 22, 0, 0).isoformat()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timestamp, app_name, window_title FROM logs WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp",
        (start, end),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def _detect_effective_app(app_name, window_title):
    """The monitor often records mismatched app_name/window_title.
    The window_title frequently contains the REAL app and content.
    Extract the effective app from the title when possible."""
    title = (window_title or "").strip()
    title_lower = title.lower()

    # Skip noise titles
    if not title or "window server statusindicator" in title_lower:
        return app_name, ""

    # Title often starts with "AppName ActualContent"
    # e.g. "Google Chrome Amazon.com: ..." or "Code docker-compose.yml — project"
    # or "Keepassxc Prague.doc [Locked] - Keepassxc"
    known_prefixes = [
        "google chrome", "code", "terminal", "keepassxc", "steam helper",
        "steam", "discord", "finder", "fusion", "simplify3d", "vlc",
        "inav-configurator", "loom", "messages", "telegram", "slack",
        "microsoft teams", "firefox", "monodraw", "notes"
    ]

    for prefix in known_prefixes:
        if title_lower.startswith(prefix + " "):
            effective_app = prefix
            effective_title = title[len(prefix):].strip()
            # Capitalize app name to match convention
            app_map = {
                "google chrome": "Google Chrome",
                "code": "Code",
                "terminal": "Terminal",
                "keepassxc": "KeePassXC",
                "steam helper": "Steam Helper",
                "steam": "Steam",
                "discord": "Discord",
                "finder": "Finder",
                "fusion": "Fusion",
                "simplify3d": "Simplify3D",
                "vlc": "VLC",
                "inav-configurator": "inav-configurator",
                "loom": "Loom",
                "messages": "Messages",
                "telegram": "Telegram",
                "slack": "Slack",
                "microsoft teams": "Microsoft Teams",
                "firefox": "Firefox",
                "monodraw": "Monodraw",
                "notes": "Notes",
            }
            return app_map.get(effective_app, effective_app), effective_title

    return app_name, title


def classify_entry(app_name, window_title, rules):
    """Classify a single entry as 'work', 'personal', 'ambiguous', or 'ignore'."""
    raw_app = (app_name or "").strip()
    raw_title = (window_title or "").strip()

    # Skip pure noise
    if not raw_title or "window server statusindicator" in raw_title.lower():
        # With no title info, classify based on app_name alone
        app = raw_app
        title = ""
    else:
        # Detect effective app from title (handles mismatched app/title)
        app, title = _detect_effective_app(raw_app, raw_title)

    combined = f"{app} {title}".lower()

    # Check ignore first
    for ignore_app in rules.get("ignore", {}).get("apps", []):
        if app.lower() == ignore_app.lower():
            return "ignore", app

    # Check personal apps
    for personal_app in rules.get("personal", {}).get("apps", []):
        if app.lower() == personal_app.lower():
            return "personal", app

    # Check work apps (unconditional)
    for work_app in rules.get("work", {}).get("apps", []):
        if app.lower() == work_app.lower():
            return "work", app

    # Check conditional work apps (e.g., Code only if window title matches)
    for cond_app, keywords in rules.get("work", {}).get("app_conditional", {}).items():
        if app.lower() == cond_app.lower():
            for kw in keywords:
                if kw.lower() in combined:
                    return "work", app
            for pk in rules.get("personal", {}).get("chrome_keywords", []):
                if pk.lower() in combined:
                    return "personal", app
            return "ambiguous", app

    # Chrome / browser — classify by title keywords
    # Check personal first so personal infra (cloudflare, botnique, etc.) wins
    if app.lower() == "google chrome":
        title_lower = title.lower() if title else combined
        for pk in rules.get("personal", {}).get("chrome_keywords", []):
            if pk.lower() in title_lower:
                return "personal", app
        for kw in rules.get("work", {}).get("chrome_keywords", []):
            if kw.lower() in title_lower:
                return "work", app
        for ak in rules.get("ambiguous", {}).get("chrome_keywords", []):
            if ak.lower() in title_lower:
                return "ambiguous", app
        return "ambiguous", app

    # Terminal — check title for context clues
    if app.lower() == "terminal":
        title_lower = title.lower() if title else ""
        for kw in rules.get("work", {}).get("chrome_keywords", []):
            if kw.lower() in title_lower:
                return "work", app
        for pk in rules.get("personal", {}).get("chrome_keywords", []):
            if pk.lower() in title_lower:
                return "personal", app
        for personal_app in rules.get("personal", {}).get("apps", []):
            if personal_app.lower() in title_lower:
                return "personal", app
        return "ambiguous", app

    # Ambiguous apps
    for amb_app in rules.get("ambiguous", {}).get("apps", []):
        if app.lower() == amb_app.lower():
            return "ambiguous", app

    return "ambiguous", app


def group_into_blocks(classified_entries, gap_tolerance_min=GAP_TOLERANCE_MIN):
    """Group consecutive entries of the same classification into time blocks."""
    if not classified_entries:
        return []

    blocks = []
    current_class = classified_entries[0]["classification"]
    current_start = classified_entries[0]["timestamp"]
    current_end = classified_entries[0]["timestamp"]
    current_apps = defaultdict(int)
    current_titles = []

    app = classified_entries[0]["app_name"]
    current_apps[app] += 1
    current_titles.append(classified_entries[0]["window_title"])

    for entry in classified_entries[1:]:
        ts = entry["timestamp"]
        cls = entry["classification"]
        gap = (ts - current_end).total_seconds() / 60

        # Continue block if same classification and gap is small
        if cls == current_class and gap <= gap_tolerance_min:
            current_end = ts
            current_apps[entry["app_name"]] += 1
            current_titles.append(entry["window_title"])
        else:
            # Save current block
            blocks.append(
                {
                    "classification": current_class,
                    "start": current_start,
                    "end": current_end,
                    "duration_min": (current_end - current_start).total_seconds() / 60,
                    "apps": dict(current_apps),
                    "sample_titles": _dedupe_titles(current_titles, max_count=8),
                }
            )
            # Start new block
            current_class = cls
            current_start = ts
            current_end = ts
            current_apps = defaultdict(int)
            current_apps[entry["app_name"]] += 1
            current_titles = [entry["window_title"]]

    # Final block
    blocks.append(
        {
            "classification": current_class,
            "start": current_start,
            "end": current_end,
            "duration_min": (current_end - current_start).total_seconds() / 60,
            "apps": dict(current_apps),
            "sample_titles": _dedupe_titles(current_titles, max_count=8),
        }
    )

    return blocks


def _dedupe_titles(titles, max_count=8):
    """Return up to max_count unique, non-empty titles."""
    seen = set()
    result = []
    for t in titles:
        t = (t or "").strip()
        if not t or t in seen or t.lower() == "window server statusindicator":
            continue
        seen.add(t)
        result.append(t)
        if len(result) >= max_count:
            break
    return result


def merge_work_blocks(blocks, gap_tolerance_min=GAP_TOLERANCE_MIN):
    """Merge work blocks that are within gap_tolerance of each other,
    regardless of how many non-work blocks sit between them."""
    if len(blocks) < 2:
        return blocks

    # Collect indices of work blocks
    work_indices = [i for i, b in enumerate(blocks) if b["classification"] == "work"]
    if len(work_indices) < 2:
        return blocks

    # Find pairs of work blocks to merge (time gap <= tolerance)
    merge_ranges = []  # list of (start_block_idx, end_block_idx) to merge
    i = 0
    while i < len(work_indices):
        chain_start = work_indices[i]
        chain_end = work_indices[i]
        # Extend chain while next work block is within gap tolerance
        while i + 1 < len(work_indices):
            curr_work = blocks[work_indices[i]]
            next_work = blocks[work_indices[i + 1]]
            gap = (next_work["start"] - curr_work["end"]).total_seconds() / 60
            if gap <= gap_tolerance_min:
                chain_end = work_indices[i + 1]
                i += 1
            else:
                break
        if chain_end > chain_start:
            merge_ranges.append((chain_start, chain_end))
        i += 1

    # Build merged block list
    merged_set = set()
    merged_blocks = {}
    for rstart, rend in merge_ranges:
        # Merge all work blocks in this range into one
        work_in_range = [blocks[j] for j in range(rstart, rend + 1) if blocks[j]["classification"] == "work"]
        combined = {
            "classification": "work",
            "start": work_in_range[0]["start"],
            "end": work_in_range[-1]["end"],
            "duration_min": (work_in_range[-1]["end"] - work_in_range[0]["start"]).total_seconds() / 60,
            "apps": {},
            "sample_titles": [],
        }
        for wb in work_in_range:
            for app, cnt in wb["apps"].items():
                combined["apps"][app] = combined["apps"].get(app, 0) + cnt
            combined["sample_titles"] = _dedupe_titles(
                combined["sample_titles"] + wb["sample_titles"]
            )
        merged_blocks[rstart] = combined
        for j in range(rstart, rend + 1):
            if blocks[j]["classification"] == "work":
                merged_set.add(j)

    # Rebuild block list, replacing merged work blocks and keeping non-work blocks
    result = []
    i = 0
    while i < len(blocks):
        if i in merged_blocks:
            result.append(merged_blocks[i])
            # Skip all blocks in this merge range
            rend = [rend for rstart, rend in merge_ranges if rstart == i][0]
            # Add non-work blocks that were between merged work blocks
            for j in range(i, rend + 1):
                if blocks[j]["classification"] != "work":
                    result.append(blocks[j])
            i = rend + 1
        elif i in merged_set:
            i += 1  # skip, already merged
        else:
            result.append(blocks[i])
            i += 1

    return result


def get_timetagger_entries(date_str, env):
    """Fetch TimeTagger entries for the given date."""
    d = datetime.strptime(date_str, "%Y%m%d").date()
    start_epoch = int(datetime(d.year, d.month, d.day, 0, 0, 0).timestamp())
    end_epoch = int(datetime(d.year, d.month, d.day, 23, 59, 59).timestamp())

    base_url = env.get("TIMETAGGER_URL", "").rstrip("/")
    token = env.get("TIMETAGGER_API_TOKEN", "")
    cf_id = env.get("CF_ACCESS_CLIENT_ID", "")
    cf_secret = env.get("CF_ACCESS_CLIENT_SECRET", "")

    if not base_url or not token:
        return None

    url = f"{base_url}/api/v2/records?timerange={start_epoch}-{end_epoch}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "work-log-analyzer/1.0")
    req.add_header("authtoken", token)
    if cf_id:
        req.add_header("CF-Access-Client-Id", cf_id)
    if cf_secret:
        req.add_header("CF-Access-Client-Secret", cf_secret)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        entries = []
        for r in data.get("records", []):
            t1 = r.get("t1", 0)
            t2 = r.get("t2", 0)
            if t2 <= t1:
                continue
            entries.append(
                {
                    "start": datetime.fromtimestamp(t1),
                    "end": datetime.fromtimestamp(t2),
                    "duration_h": (t2 - t1) / 3600,
                    "description": r.get("ds", ""),
                }
            )
        return sorted(entries, key=lambda e: e["start"])
    except Exception as e:
        print(f"  Warning: Could not fetch TimeTagger data: {e}", file=sys.stderr)
        return None


def load_screenshot_index(date_str):
    """Build a sorted list of (datetime, filepath) for the date's screenshots."""
    ss_dir = os.path.join(SCREENSHOTS_DIR, date_str)
    index = []
    if not os.path.isdir(ss_dir):
        return index
    for f in sorted(os.listdir(ss_dir)):
        if f.startswith(date_str + "_") and f.endswith(".png"):
            try:
                time_part = f[len(date_str) + 1 : -4]  # HHMMSS
                hour = int(time_part[0:2])
                minute = int(time_part[2:4])
                second = int(time_part[4:6])
                d = datetime.strptime(date_str, "%Y%m%d").date()
                ts = datetime(d.year, d.month, d.day, hour, minute, second)
                index.append((ts, os.path.join(ss_dir, f)))
            except (ValueError, IndexError):
                pass
    return index


def find_closest_screenshot(target_dt, ss_index):
    """Find the screenshot closest to target_dt. Returns filepath or None."""
    if not ss_index:
        return None
    best = None
    best_delta = None
    for ts, path in ss_index:
        delta = abs((ts - target_dt).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best = path
        elif delta > best_delta:
            break  # sorted, so we passed the closest
    return best


def count_screenshots(date_str):
    """Count working-hours screenshots for the date."""
    ss_dir = os.path.join(SCREENSHOTS_DIR, date_str)
    if not os.path.isdir(ss_dir):
        return 0
    count = 0
    for f in os.listdir(ss_dir):
        if f.startswith(date_str + "_") and f.endswith(".png"):
            try:
                hour = int(f[len(date_str) + 1 : len(date_str) + 3])
                if 7 <= hour < 22:
                    count += 1
            except ValueError:
                pass
    return count


def format_time(dt):
    return dt.strftime("%H:%M")


def format_duration(minutes):
    h = int(minutes // 60)
    m = int(minutes % 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def summarize_apps(apps_dict):
    """Return a short summary of the top apps in a block."""
    sorted_apps = sorted(apps_dict.items(), key=lambda x: -x[1])
    top = sorted_apps[:3]
    return ", ".join(f"{app}" for app, _ in top)


def generate_report(date_str, work_blocks, ambiguous_blocks, personal_blocks, tt_entries, screenshot_count, ss_index=None):
    """Generate markdown report for a single day."""
    d = datetime.strptime(date_str, "%Y%m%d").date()
    dow = d.strftime("%a")

    lines = [f"# Work Log Analysis: {d.isoformat()} ({dow})", ""]

    # Screenshot count
    lines.append(f"**Screenshots (7am-10pm):** {screenshot_count}")
    lines.append("")

    # Existing TimeTagger entries
    lines.append("## Existing TimeTagger Entries")
    if tt_entries is None:
        lines.append("*(could not fetch from API)*")
    elif not tt_entries:
        lines.append("*(none)*")
    else:
        total_tt = sum(e["duration_h"] for e in tt_entries)
        total_tt_min = total_tt * 60
        lines.append(f"| # | Start | End | Duration | Description |")
        lines.append(f"|---|-------|-----|----------|-------------|")
        for i, e in enumerate(tt_entries, 1):
            dur = format_duration(e["duration_h"] * 60)
            lines.append(
                f"| {i} | {format_time(e['start'])} | {format_time(e['end'])} | {dur} | {e['description']} |"
            )
        lines.append(f"\n**Total logged: {format_duration(total_tt_min)} ({total_tt:.1f}h)**")
    lines.append("")

    # Detected work blocks
    lines.append("## Detected Work Blocks")
    if not work_blocks:
        lines.append("*(no work activity detected)*")
    else:
        total_work = sum(b["duration_min"] for b in work_blocks)
        lines.append(f"| # | Start | End | Duration | Apps | Screenshot | Activity Clues |")
        lines.append(f"|---|-------|-----|----------|------|------------|----------------|")
        for i, b in enumerate(work_blocks, 1):
            dur = format_duration(b["duration_min"])
            apps = summarize_apps(b["apps"])
            titles = "; ".join(b["sample_titles"][:3])
            if len(titles) > 80:
                titles = titles[:77] + "..."
            ss_link = ""
            if ss_index:
                ss_path = find_closest_screenshot(b["start"], ss_index)
                if ss_path:
                    rel = os.path.relpath(ss_path, OUTPUT_DIR)
                    ss_link = f"[{format_time(b['start'])}]({rel})"
            lines.append(
                f"| {i} | {format_time(b['start'])} | {format_time(b['end'])} | {dur} | {apps} | {ss_link} | {titles} |"
            )
        lines.append(f"\n**Total detected work: {format_duration(total_work)} ({total_work / 60:.1f}h)**")
    lines.append("")

    # Ambiguous blocks (only show significant ones)
    sig_ambiguous = [b for b in ambiguous_blocks if b["duration_min"] >= 2]
    if sig_ambiguous:
        lines.append("## Ambiguous Activity (review if needed)")
        for b in sig_ambiguous:
            apps = summarize_apps(b["apps"])
            titles = "; ".join(b["sample_titles"][:2])
            if len(titles) > 60:
                titles = titles[:57] + "..."
            ss_link = ""
            if ss_index:
                ss_path = find_closest_screenshot(b["start"], ss_index)
                if ss_path:
                    rel = os.path.relpath(ss_path, OUTPUT_DIR)
                    ss_link = f" ([screenshot]({rel}))"
            lines.append(
                f"- {format_time(b['start'])}-{format_time(b['end'])} ({format_duration(b['duration_min'])}): {apps} — {titles}{ss_link}"
            )
        lines.append("")

    # Personal summary (collapsed)
    if personal_blocks:
        total_personal = sum(b["duration_min"] for b in personal_blocks)
        lines.append("## Personal Activity (excluded)")
        lines.append(f"**Total: {format_duration(total_personal)}**")
        personal_apps = defaultdict(int)
        for b in personal_blocks:
            for app, cnt in b["apps"].items():
                personal_apps[app] += cnt
        top_personal = sorted(personal_apps.items(), key=lambda x: -x[1])[:5]
        lines.append(f"Top apps: {', '.join(app for app, _ in top_personal)}")
        lines.append("")

    return "\n".join(lines)


def get_remaining_dates():
    """Parse the checklist for unchecked dates."""
    if not os.path.exists(CHECKLIST_PATH):
        print(f"Checklist not found: {CHECKLIST_PATH}", file=sys.stderr)
        return []

    dates = []
    with open(CHECKLIST_PATH) as f:
        for line in f:
            match = re.match(r"\|\s*\[ \]\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|", line)
            if match:
                d = match.group(1).replace("-", "")
                dates.append(d)
    return dates


def analyze_day(date_str, rules, env, gap_tolerance=GAP_TOLERANCE_MIN):
    """Run full analysis for a single day."""
    print(f"\nAnalyzing {date_str}...")

    # Step 1: Extract activity
    rows = get_activity_entries(date_str)
    if not rows:
        print(f"  No activity log entries found for {date_str}")
        return

    # Step 2: Classify
    classified = []
    for ts_str, app, title in rows:
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        cls, effective_app = classify_entry(app, title, rules)
        if cls == "ignore":
            continue
        classified.append(
            {
                "timestamp": ts,
                "app_name": effective_app or app or "",
                "window_title": title or "",
                "classification": cls,
            }
        )

    if not classified:
        print(f"  No classifiable entries for {date_str}")
        return

    # Step 3: Group into blocks
    blocks = group_into_blocks(classified, gap_tolerance)
    blocks = merge_work_blocks(blocks, gap_tolerance)

    work_blocks = [b for b in blocks if b["classification"] == "work" and b["duration_min"] >= 1]
    ambiguous_blocks = [b for b in blocks if b["classification"] == "ambiguous"]
    personal_blocks = [b for b in blocks if b["classification"] == "personal"]

    # Step 4: TimeTagger cross-reference
    tt_entries = get_timetagger_entries(date_str, env)

    # Step 5: Screenshots
    ss_count = count_screenshots(date_str)
    ss_index = load_screenshot_index(date_str)

    # Step 6: Generate report
    report = generate_report(
        date_str, work_blocks, ambiguous_blocks, personal_blocks, tt_entries, ss_count, ss_index
    )

    # Save
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"analysis_{date_str}.md")
    with open(output_path, "w") as f:
        f.write(report)

    # Print summary
    total_work = sum(b["duration_min"] for b in work_blocks)
    total_ambiguous = sum(b["duration_min"] for b in ambiguous_blocks)
    tt_total = sum(e["duration_h"] for e in tt_entries) if tt_entries else 0
    print(f"  Activity entries: {len(classified)}")
    print(f"  Work: {format_duration(total_work)} | Ambiguous: {format_duration(total_ambiguous)} | Logged: {tt_total:.1f}h")
    print(f"  Report: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Work Log Analyzer")
    parser.add_argument("dates", nargs="*", help="YYYYMMDD date(s) or start end range")
    parser.add_argument("--remaining", action="store_true", help="Process unchecked days from checklist")
    parser.add_argument("--gap", type=int, default=GAP_TOLERANCE_MIN, help="Gap tolerance in minutes (default: 5)")
    args = parser.parse_args()

    gap_tolerance = args.gap

    rules = load_classifier()
    env = load_env()

    if args.remaining:
        dates = get_remaining_dates()
        if not dates:
            print("No remaining unchecked dates found in checklist.")
            return
        print(f"Found {len(dates)} unchecked dates to process.")
    elif len(args.dates) == 2:
        # Date range
        start = datetime.strptime(args.dates[0], "%Y%m%d").date()
        end = datetime.strptime(args.dates[1], "%Y%m%d").date()
        dates = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                dates.append(current.strftime("%Y%m%d"))
            current += timedelta(days=1)
    elif len(args.dates) == 1:
        dates = [args.dates[0]]
    else:
        parser.print_help()
        return

    for date_str in dates:
        analyze_day(date_str, rules, env, gap_tolerance)

    print(f"\nDone. Processed {len(dates)} day(s).")


if __name__ == "__main__":
    main()
