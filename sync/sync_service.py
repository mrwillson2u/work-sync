#!/usr/bin/env python3
"""
TimeTagger ↔ Coda bi-directional sync service.

Runs every SYNC_INTERVAL_SEC (default 60s) and:
  Phase 1: TT → Coda  (upsert new/modified TT records into Coda TimeTagger Data table)
  Phase 2: Coda → TT   (push tag edits made in Coda back to TT descriptions)
  Phase 3: Task reassignments (propagate project/WO changes from All Tasks to TT Data rows)

Usage:
    python sync_service.py              # run continuous sync loop
    python sync_service.py --once       # run one sync cycle and exit
    python sync_service.py --full       # full sync (ignore last-sync timestamp)
"""

import json
import logging
import os
import sys
import time
from datetime import datetime

import config
import tt_client
import coda_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sync")


def load_state():
    """Load last sync timestamps from state file."""
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    """Persist sync state."""
    os.makedirs(os.path.dirname(config.STATE_FILE) or ".", exist_ok=True)
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def phase1_tt_to_coda(state, full=False):
    """Sync TimeTagger records to Coda TimeTagger Data table."""
    log.info("Phase 1: TT → Coda")

    last_sync = 0 if full else state.get("last_tt_sync", 0)

    # Fetch modified TT records
    if last_sync:
        tt_records = tt_client.get_updates(last_sync)
    else:
        # Full sync: get everything from 2025-06-01
        tt_records = tt_client.get_records(1748736000, int(time.time()))

    if not tt_records:
        log.info("  No new/modified TT records")
        return 0

    log.info("  %d TT records to process", len(tt_records))

    # Load existing Coda rows (keyed by TT key)
    coda_rows = coda_client.get_tt_data_rows()

    inserted = 0
    updated = 0
    skipped = 0

    for rec in tt_records:
        tt_key = rec.get("key", "")
        if not tt_key:
            continue

        t1, t2 = rec.get("t1", 0), rec.get("t2", 0)
        ds = rec.get("ds", "")
        mt = rec.get("mt", 0)
        parsed = config.parse_tags(ds)

        existing = coda_rows.get(tt_key)

        if existing:
            # Compare timestamps — only update if TT is newer
            coda_mt = existing["values"].get(config.TT_DATA_COLS["mt"], 0)
            if isinstance(coda_mt, (int, float)) and mt > coda_mt:
                try:
                    coda_client.upsert_tt_data_row(rec, parsed, existing["row_id"])
                    updated += 1
                    log.debug("  Updated %s", tt_key)
                except Exception as e:
                    log.error("  Failed to update %s: %s", tt_key, e)
            else:
                skipped += 1
        else:
            # New record — insert
            try:
                coda_client.upsert_tt_data_row(rec, parsed)
                inserted += 1
                log.debug("  Inserted %s", tt_key)
            except Exception as e:
                log.error("  Failed to insert %s: %s", tt_key, e)

    log.info("  Phase 1 done: %d inserted, %d updated, %d skipped", inserted, updated, skipped)
    state["last_tt_sync"] = time.time()
    return inserted + updated


def phase2_coda_to_tt(state):
    """Phase 2 is no longer needed.

    Tag columns in Coda are now formulas (auto-parsed from ds).
    They can't be edited by a human. Tag reassignments are handled
    by Phase 3 (task moves → rebuild ds → push to both Coda and TT).

    Keeping this as a no-op for now in case we need it later.
    """
    log.info("Phase 2: skipped (tag columns are Coda formulas)")
    return 0


def phase3_task_reassignments(state):
    """Propagate project/WO changes from All Tasks to TimeTagger Data rows.

    When a task moves to a different project (or a project moves to a different WO),
    this updates all TT Data rows for that task with the correct #pro-XX, #wo-XX,
    and client tags. Phase 2 then picks up the change and pushes it to TT.

    Lookup chain: task → project name → Projects table → project_id + WO + client
    """
    log.info("Phase 3: Task reassignment check")

    tasks = coda_client.get_all_tasks()
    clients = coda_client.get_clients()
    projects = coda_client.get_projects(clients)
    coda_rows = coda_client.get_tt_data_rows()

    def _norm(v):
        return (v[0] if v else "") if isinstance(v, list) else (v or "")

    updates = 0
    for tt_key, row in coda_rows.items():
        vals = row["values"]
        task_tag = _norm(vals.get(config.TT_DATA_COLS["task_id"], ""))
        if not task_tag or not task_tag.startswith("#tsk-"):
            continue

        # Find the matching task in All Tasks
        tsk_id = task_tag.replace("#", "").upper()  # e.g., TSK-213
        task = tasks.get(tsk_id)
        if not task:
            continue

        # Look up the task's current project → get expected tags
        project_name = task.get("project", "")
        proj_info = projects.get(project_name, {})
        expected_proj = proj_info.get("project_id", "")
        expected_wo = proj_info.get("work_order_id", "")
        expected_client = proj_info.get("client_tag", "")

        # If task has no project assigned, skip
        if not expected_proj:
            continue

        # Compare against what's in the TT Data row
        current_proj = _norm(vals.get(config.TT_DATA_COLS["project_id"], ""))
        current_wo = _norm(vals.get(config.TT_DATA_COLS["work_order_id"], ""))
        current_client = _norm(vals.get(config.TT_DATA_COLS["client_tag"], ""))

        if (current_proj != expected_proj
                or current_wo != expected_wo
                or current_client != expected_client):
            # Update the TT Data row with correct tags
            ds = _norm(vals.get(config.TT_DATA_COLS["ds"], ""))
            ds_clean = config.clean_description(ds)
            new_ds = config.rebuild_description(
                ds_clean, task_tag, expected_proj, expected_wo, expected_client
            )
            try:
                # Update ds in Coda (formulas auto-parse tags)
                coda_client.update_tt_data_tags(
                    row["row_id"], task_tag, expected_proj, expected_wo, expected_client, new_ds
                )
                # Also update TT so both sides match (prevents Phase 1 from reverting)
                tt_rec = {"key": tt_key, "ds": new_ds, "mt": time.time(),
                          "t1": vals.get(config.TT_DATA_COLS["t1"], 0),
                          "t2": vals.get(config.TT_DATA_COLS["t2"], 0),
                          "st": vals.get(config.TT_DATA_COLS["st"], 0)}
                tt_client.put_records([tt_rec])
                updates += 1
                log.info("  Reassigned %s: %s → %s %s %s",
                         tt_key, current_proj, expected_proj, expected_wo, expected_client)
            except Exception as e:
                log.error("  Failed to reassign %s: %s", tt_key, e)

    log.info("  Phase 3 done: %d reassignments propagated", updates)
    return updates


def _iso_to_epoch(iso_str):
    """Convert ISO 8601 datetime string to epoch. Returns 0 on failure."""
    if not iso_str:
        return 0
    try:
        # Handle various ISO formats
        iso_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0


def run_sync(full=False):
    """Run one complete sync cycle."""
    state = load_state()
    start = time.time()

    try:
        p1 = phase1_tt_to_coda(state, full=full)
        p2 = phase2_coda_to_tt(state)
        p3 = phase3_task_reassignments(state)

        state["last_sync"] = time.time()
        save_state(state)

        elapsed = time.time() - start
        log.info("Sync complete in %.1fs (P1: %d, P2: %d, P3: %d)", elapsed, p1, p2, p3)
    except Exception as e:
        log.error("Sync cycle failed: %s", e, exc_info=True)


def main():
    once = "--once" in sys.argv
    full = "--full" in sys.argv

    log.info("Starting TT ↔ Coda sync service (interval=%ds, once=%s, full=%s)",
             config.SYNC_INTERVAL_SEC, once, full)

    if once:
        run_sync(full=full)
        return

    while True:
        run_sync(full=full)
        full = False  # only first run is full
        log.info("Sleeping %ds until next sync...", config.SYNC_INTERVAL_SEC)
        time.sleep(config.SYNC_INTERVAL_SEC)


if __name__ == "__main__":
    main()
