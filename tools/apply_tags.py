#!/usr/bin/env python3
"""
Apply tags to TimeTagger entries by:
1. Creating new Coda tasks for each unique TT description
2. Updating TT entries with #tsk-XXX #pro-XX #wo-XX #nsight tags

Usage:
    python3 apply_tags.py --dry-run    # preview changes
    python3 apply_tags.py              # apply changes
"""

import json
import os
import sys
import urllib.request
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
ENV_PATH = os.path.join(REPO_DIR, ".env")

CODA_DOC_ID = "OSAZiA68PX"
CODA_TASKS_TABLE = "grid-L6CM1HyWMk"
CODA_API_BASE = "https://coda.io/apis/v1"

# Project name -> (PRO-XX, WO-XX) mapping
PROJECT_MAP = {
    "PRO-40": {"name": "QA bug testing for portal platform", "wo": "WO-13"},
    "PRO-41": {"name": "Wrap up de-identification service", "wo": "WO-13"},
    "PRO-42": {"name": "Meetings/Admin", "wo": "WO-13"},
    "PRO-43": {"name": "Quality Dashboard for J&J Demo", "wo": "WO-13"},
    "PRO-44": {"name": "OR Live Updates", "wo": "WO-14"},
    "PRO-45": {"name": "Complete new recording service to replace Justin's version", "wo": "WO-14"},
    "PRO-47": {"name": "Post Processor Stability Updates", "wo": "WO-14"},
    "PRO-50": {"name": "Thor Documentation", "wo": "WO-15"},
    "PRO-51": {"name": "Meetings/Admin", "wo": "WO-14"},
}

# WO-14 starts Feb 2 2026
WO14_START_EPOCH = 1769990400

# Descriptions that need date-based WO split (standups)
# Before WO14_START_EPOCH -> PRO-42 (WO-13), after -> PRO-51 (WO-14)
DATE_SPLIT_DESCS = {"Standup", "Standup #tsk-168 #pro-34 #nsight"}

# Description -> project mapping (from tagging_plan.md)
DESC_TO_PROJECT = {
    # PRO-40
    "bug testing on nsight platform": "PRO-40",
    "Platform dev testing": "PRO-40",
    "J&J Demo testing": "PRO-40",
    # PRO-41
    "Cleaning up de-identification service": "PRO-41",
    "Organize benchmark data": "PRO-41",
    "Implement black box de-id on thor": "PRO-41",
    "Build stream-generator to test de-identification service on thor": "PRO-41",
    # PRO-42 (WO-13 meetings, Jan)
    "J&J demo dry run meeting": "PRO-42",
    "J&J Demo email": "PRO-42",
    # PRO-51 (WO-14 meetings, Feb+)
    "Progress meeting": "PRO-51",
    "Email and chat communication": "PRO-51",
    "Calendar, nsight platform config": "PRO-51",
    # PRO-43
    "Nsight platform dev and post-processor updates": "PRO-43",
    # PRO-44
    "Planning orlive merge": "PRO-44",
    "Implementing orlive merge": "PRO-44",
    "Test updated code": "PRO-44",
    "Hook up rtsp stream": "PRO-44",
    "Sort out test instance for video streams": "PRO-44",
    "Stream testing": "PRO-44",
    "OR live user authentication": "PRO-44",
    "OR Live Auth": "PRO-44",
    "OR Live Stream Implemenation": "PRO-44",
    "Developing mediamtx streamer for or": "PRO-44",
    "Testing after merging upstream changes": "PRO-44",
    "Fixing PR issues": "PRO-44",
    "Address test result issues in or-live merge": "PRO-44",
    "Styling for orlive multi-room": "PRO-44",
    "orlive test videos": "PRO-44",
    "Make modifications to orlive from feedback": "PRO-44",
    "orlive followup review and feedback": "PRO-44",
    "Test and push test videos": "PRO-44",
    "Finish testing repo to submit pr": "PRO-44",
    "Use dummy data for demo": "PRO-44",
    "Troubleshoot issues on nsight-platform": "PRO-44",
    "FIx dummy data": "PRO-44",
    "OR Live PR work and code fixes": "PRO-44",
    "OR Live PR review": "PRO-44",
    "Calendar, email, OR Live planning": "PRO-44",
    "Planning for local video service in OR Live": "PRO-44",
    "Fleet View Kickoff Meeting": "PRO-44",
    "Fleet view Meeting": "PRO-44",
    # PRO-45
    "Implement streaming funnctionality": "PRO-45",
    "Develop new recording service": "PRO-45",
    "Get streaming working": "PRO-45",
    "spin up 5 stream pseudo rtsp server for testing and test streams": "PRO-45",
    "Fix camera-recorder not recording issue": "PRO-45",
    "Fix camera scheduling": "PRO-45",
    "Troubleeshoot Camera Recorder": "PRO-45",
    # PRO-47
    "Clean/organize post processor code": "PRO-47",
    "Committing code to post processor updated on sisyphus": "PRO-47",
    "Troubleshoot post-processopr": "PRO-47",
    "Troubleshoot post-processor": "PRO-47",
    "Fix post-processor issues": "PRO-47",
    "Check on and resolve post-processor camera fps issue": "PRO-47",
    "testing post processor for bugs": "PRO-47",
    "Investigate queue issue": "PRO-47",
    "Bug fixes and improvements to post-processor": "PRO-47",
    # PRO-50
    "Plan deployment plan for thor": "PRO-50",
    "Cover plan for thor install": "PRO-50",
    "Meet with Amy to go over documentation plan": "PRO-50",
    "Audit install plan and prep email": "PRO-50",
    "Audit install plan, TimeTagger logging": "PRO-50",
}

# Unassigned (no WO)
UNASSIGNED = {
    "Research Cameras",
    "Reserch Camera options and create BOM variations",
}


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


def coda_request(method, path, env, data=None):
    url = f"{CODA_API_BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {env['CODA_API_TOKEN']}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def tt_request(method, path, env, data=None):
    base_url = env.get("TIMETAGGER_URL", "").rstrip("/")
    url = f"{base_url}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", "work-log-analyzer/1.0")
    req.add_header("authtoken", env["TIMETAGGER_API_TOKEN"])
    if env.get("CF_ACCESS_CLIENT_ID"):
        req.add_header("CF-Access-Client-Id", env["CF_ACCESS_CLIENT_ID"])
    if env.get("CF_ACCESS_CLIENT_SECRET"):
        req.add_header("CF-Access-Client-Secret", env["CF_ACCESS_CLIENT_SECRET"])
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def get_next_task_id(env):
    """Find the highest TSK-XXX in Coda and return the next one."""
    max_id = 0
    next_page = f"/docs/{CODA_DOC_ID}/tables/{CODA_TASKS_TABLE}/rows?limit=500&valueFormat=simpleWithArrays"
    while next_page:
        result = coda_request("GET", next_page, env)
        for row in result.get("items", []):
            vals = row.get("values", {})
            tid = vals.get("c-Fb6N3kMNW3", "")
            if tid and tid.startswith("TSK-"):
                try:
                    num = int(tid.split("-")[1])
                    if num > max_id:
                        max_id = num
                except ValueError:
                    pass
        next_page = result.get("nextPageLink")
        if next_page:
            next_page = next_page.replace(CODA_API_BASE, "")
    return max_id + 1


def get_tt_records(env):
    """Fetch all TT records from Jan 1 2026."""
    start = 1767254400
    end = int(time.time())
    return tt_request("GET", f"/api/v2/records?timerange={start}-{end}", env).get("records", [])


def main():
    dry_run = "--dry-run" in sys.argv
    env = load_env()

    if dry_run:
        print("=== DRY RUN — no changes will be made ===\n")

    # Step 1: Get TT records and group by unique description
    print("Fetching TimeTagger records...")
    records = get_tt_records(env)
    print(f"  {len(records)} records")

    # Group by description
    from collections import defaultdict
    desc_records = defaultdict(list)
    for r in records:
        ds = r.get("ds", "").strip()
        t1, t2 = r.get("t1", 0), r.get("t2", 0)
        if t2 <= t1 or ds.startswith("HIDDEN"):
            continue
        desc_records[ds].append(r)

    print(f"  {len(desc_records)} unique descriptions (excluding HIDDEN)")

    # Step 2: Get next task ID
    print("Checking Coda for next task ID...")
    next_id = get_next_task_id(env)
    print(f"  Next task ID: TSK-{next_id}")

    # Step 3: Create Coda tasks and build tag map
    import re
    tag_map = {}  # description -> tag string (for non-date-split entries)
    record_tag_map = {}  # record key -> tag string (for date-split entries)
    tasks_to_create = []
    clean_to_task = {}  # "clean_desc|proj_id" -> tsk_id (dedup)

    def get_or_create_task(clean_desc, proj_id):
        nonlocal next_id
        proj = PROJECT_MAP[proj_id]
        wo_id = proj["wo"]
        dedup_key = f"{clean_desc}|{proj_id}"
        if dedup_key in clean_to_task:
            tsk_id = clean_to_task[dedup_key]
        else:
            tsk_id = f"TSK-{next_id}"
            clean_to_task[dedup_key] = tsk_id
            tasks_to_create.append({
                "tsk_id": tsk_id,
                "name": clean_desc,
                "project": proj["name"],
                "wo": wo_id,
                "proj_id": proj_id,
            })
            next_id += 1
        return f"{clean_desc} #{tsk_id.lower()} #{proj_id.lower()} #{wo_id.lower()} #nsight"

    for ds in sorted(desc_records.keys()):
        if ds in UNASSIGNED:
            cleaned = re.sub(r'\s*#\S+', '', ds).strip()
            tag_map[ds] = f"{cleaned} #unassigned"
            continue

        clean_desc = re.sub(r'\s*#\S+', '', ds).strip()

        # Date-split descriptions: tag each record individually
        if ds in DATE_SPLIT_DESCS:
            for r in desc_records[ds]:
                t1 = r.get("t1", 0)
                if t1 < WO14_START_EPOCH:
                    proj_id = "PRO-42"
                else:
                    proj_id = "PRO-51"
                record_tag_map[r["key"]] = get_or_create_task(clean_desc, proj_id)
            continue

        proj_id = DESC_TO_PROJECT.get(ds)
        if not proj_id:
            print(f"  WARNING: No project mapping for \"{ds}\" — skipping")
            continue

        tag_map[ds] = get_or_create_task(clean_desc, proj_id)

    print(f"\n  {len(tasks_to_create)} new Coda tasks to create")
    print(f"  {len(tag_map)} descriptions to tag (bulk)")
    print(f"  {len(record_tag_map)} records to tag (date-split)")

    # Show summary by project
    from collections import Counter
    proj_counts = Counter()
    for t in tasks_to_create:
        proj_counts[t["proj_id"]] += 1
    print("\n  Tasks per project:")
    for pid in sorted(proj_counts.keys()):
        print(f"    {pid} ({PROJECT_MAP[pid]['name']}): {proj_counts[pid]}")

    if dry_run:
        print("\n=== TASKS TO CREATE ===")
        for t in tasks_to_create:
            print(f"  {t['tsk_id']}: \"{t['name']}\" -> {t['proj_id']} / {t['wo']}")

        print(f"\n=== TIMETAGGER TAGS TO APPLY (bulk) ===")
        for ds, tag in sorted(tag_map.items()):
            count = len(desc_records[ds])
            print(f"  ({count}x) \"{ds}\" -> \"{tag}\"")

        if record_tag_map:
            print(f"\n=== TIMETAGGER TAGS TO APPLY (date-split) ===")
            from datetime import datetime
            for key, tag in sorted(record_tag_map.items(), key=lambda x: x[1]):
                # Find the record to show its date
                for ds, recs in desc_records.items():
                    for r in recs:
                        if r["key"] == key:
                            day = datetime.fromtimestamp(r["t1"]).strftime("%Y-%m-%d")
                            print(f"  {day} \"{ds}\" -> \"{tag}\"")

        print(f"\n=== DRY RUN COMPLETE — run without --dry-run to apply ===")
        return

    # Step 4: Create tasks in Coda
    print("\nCreating Coda tasks...")
    created = 0
    for t in tasks_to_create:
        try:
            coda_request("POST", f"/docs/{CODA_DOC_ID}/tables/{CODA_TASKS_TABLE}/rows", env, {
                "rows": [{
                    "cells": [
                        {"column": "c-kYQU7nZVNj", "value": t["name"]},           # Name
                        {"column": "c-XH8JS9uHKm", "value": "Done"},              # Status
                        {"column": "c-Fb6N3kMNW3", "value": t["tsk_id"]},         # Task ID
                        {"column": "c-MwasSqxwCF", "value": f"{t['name']} #{t['tsk_id'].lower()} #{t['proj_id'].lower()} #{t['wo'].lower()} #nsight"},  # Time Tagger Description
                        {"column": "c-q3fiT312d6", "value": t["project"]},        # Project (lookup)
                        {"column": "c-1qGOTwGZeU", "value": "nSight Surgical"},   # Client (lookup)
                        {"column": "c-dJl_t7828e", "value": t["wo"]},             # Work Order (lookup)
                    ]
                }]
            })
            created += 1
            print(f"  Created {t['tsk_id']}: {t['name']}")
            time.sleep(2)  # rate limit
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"  Rate limited at {t['tsk_id']}, waiting 30s...")
                time.sleep(30)
                try:
                    coda_request("POST", f"/docs/{CODA_DOC_ID}/tables/{CODA_TASKS_TABLE}/rows", env, {
                        "rows": [{
                            "cells": [
                                {"column": "c-kYQU7nZVNj", "value": t["name"]},
                                {"column": "c-XH8JS9uHKm", "value": "Done"},
                                {"column": "c-Fb6N3kMNW3", "value": t["tsk_id"]},
                                {"column": "c-MwasSqxwCF", "value": f"{t['name']} #{t['tsk_id'].lower()} #{t['proj_id'].lower()} #{t['wo'].lower()} #nsight"},
                                {"column": "c-q3fiT312d6", "value": t["project"]},
                                {"column": "c-1qGOTwGZeU", "value": "nSight Surgical"},
                                {"column": "c-dJl_t7828e", "value": t["wo"]},
                            ]
                        }]
                    })
                    created += 1
                    print(f"  Created {t['tsk_id']}: {t['name']} (retry)")
                    time.sleep(2)
                except Exception as e2:
                    print(f"  FAILED {t['tsk_id']} (retry): {e2}")
            else:
                print(f"  FAILED {t['tsk_id']}: {e}")
        except Exception as e:
            print(f"  FAILED {t['tsk_id']}: {e}")

    print(f"\n  {created}/{len(tasks_to_create)} tasks created in Coda")

    # Step 5: Update TT records with tags
    print("\nUpdating TimeTagger entries...")
    updated = 0
    failed = 0
    batch = []
    mt = time.time()

    for ds, recs in desc_records.items():
        tag = tag_map.get(ds)
        for r in recs:
            # Check record-level tag first (date-split), then bulk tag
            rec_tag = record_tag_map.get(r["key"]) or tag
            if not rec_tag:
                continue
            r_copy = dict(r)
            r_copy["ds"] = rec_tag
            r_copy["mt"] = mt
            batch.append(r_copy)

    # Send in batches of 25
    for i in range(0, len(batch), 25):
        chunk = batch[i:i+25]
        try:
            result = tt_request("PUT", "/api/v2/records", env, chunk)
            accepted = len(result.get("accepted", []))
            fails = len(result.get("failed", []))
            updated += accepted
            failed += fails
            if fails:
                print(f"  Batch {i//25+1}: {accepted} ok, {fails} failed: {result.get('errors', [])}")
            time.sleep(0.3)
        except Exception as e:
            print(f"  Batch {i//25+1} FAILED: {e}")
            failed += len(chunk)

    print(f"\n  {updated} TT entries updated, {failed} failed")
    print("\nDone!")


if __name__ == "__main__":
    main()
