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
                # Check for pending Coda tag edit: compare tag fields vs ds tags
                coda_task = existing["values"].get(config.TT_DATA_COLS["task_id"], "")
                coda_proj = existing["values"].get(config.TT_DATA_COLS["project_id"], "")
                coda_wo = existing["values"].get(config.TT_DATA_COLS["work_order_id"], "")
                coda_client_tag = existing["values"].get(config.TT_DATA_COLS["client_tag"], "")
                # Normalize lists
                for v in [coda_task, coda_proj, coda_wo, coda_client_tag]:
                    if isinstance(v, list):
                        v = v[0] if v else ""
                coda_ds = existing["values"].get(config.TT_DATA_COLS["ds"], "")
                ds_tags = config.parse_tags(coda_ds)

                # If Coda tag fields differ from ds tags, someone edited in Coda
                # → only update time fields, don't overwrite tag edits
                pending_edit = (
                    str(coda_task) != ds_tags["task_id"]
                    or str(coda_proj) != ds_tags["project_id"]
                    or str(coda_wo) != ds_tags["work_order_id"]
                    or str(coda_client_tag) != ds_tags["client_tag"]
                )
                try:
                    coda_client.upsert_tt_data_row(
                        rec, parsed, existing["row_id"],
                        write_tags=not pending_edit
                    )
                    updated += 1
                    if pending_edit:
                        log.info("  Updated %s (time only — pending Coda tag edit)", tt_key)
                    else:
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
    """Push tag edits from Coda back to TimeTagger.

    Only processes rows edited in Coda AFTER the last Phase 2 run,
    to avoid pushing stale tag diffs from old N8N data.
    """
    log.info("Phase 2: Coda → TT")

    last_p2 = state.get("last_coda_to_tt", 0)
    coda_rows = coda_client.get_tt_data_rows()

    to_push = []
    for tt_key, row in coda_rows.items():
        # Only consider rows edited after last Phase 2 run
        row_updated = _iso_to_epoch(row["updated_at"])
        if last_p2 and row_updated < last_p2:
            continue

        vals = row["values"]
        ds = vals.get(config.TT_DATA_COLS["ds"], "")
        ds_tags = config.parse_tags(ds)

        # Get the tag fields (single source — no more "updated_*" duplication)
        def _norm(v):
            return (v[0] if v else "") if isinstance(v, list) else (v or "")

        row_task = _norm(vals.get(config.TT_DATA_COLS["task_id"], ""))
        row_proj = _norm(vals.get(config.TT_DATA_COLS["project_id"], ""))
        row_wo = _norm(vals.get(config.TT_DATA_COLS["work_order_id"], ""))
        row_client = _norm(vals.get(config.TT_DATA_COLS["client_tag"], ""))

        # If tag fields differ from what's in ds, someone edited tags in Coda
        changed = (
            row_task != ds_tags["task_id"]
            or row_proj != ds_tags["project_id"]
            or row_wo != ds_tags["work_order_id"]
            or row_client != ds_tags["client_tag"]
        )

        if changed and (row_task or row_proj):
            ds_clean = config.clean_description(ds)
            new_ds = config.rebuild_description(
                ds_clean, row_task, row_proj, row_wo, row_client
            )
            to_push.append({
                "key": tt_key,
                "new_ds": new_ds,
                "row_id": row["row_id"],
                "coda_updated": row["updated_at"],
            })

    if not to_push:
        log.info("  No Coda tag changes to push")
        return 0

    log.info("  %d records with tag changes to push to TT", len(to_push))

    # Fetch all current TT records once for conflict checking
    all_tt = tt_client.get_records(1748736000, int(time.time()) + 1)
    tt_by_key = {r["key"]: r for r in all_tt}

    pushed = 0
    skipped = 0
    for item in to_push:
        try:
            tt_rec = tt_by_key.get(item["key"])
            if not tt_rec:
                log.warning("  TT record %s not found, skipping", item["key"])
                continue

            # Conflict check: Coda updated_at vs TT mt
            coda_epoch = _iso_to_epoch(item["coda_updated"])
            tt_mt = tt_rec.get("mt", 0)

            if coda_epoch >= tt_mt:
                tt_rec["ds"] = item["new_ds"]
                tt_rec["mt"] = time.time()
                result = tt_client.put_records([tt_rec])
                if result.get("accepted"):
                    pushed += 1
                    log.debug("  Pushed tags for %s", item["key"])
            else:
                skipped += 1
                log.debug("  Skipped %s — TT is newer", item["key"])
        except Exception as e:
            log.error("  Failed to push %s: %s", item["key"], e)

    state["last_coda_to_tt"] = time.time()
    log.info("  Phase 2 done: %d pushed, %d skipped (TT newer)", pushed, skipped)
    return pushed


def phase3_task_reassignments(state):
    """Propagate project/WO changes from All Tasks to TimeTagger Data rows."""
    log.info("Phase 3: Task reassignment check")

    tasks = coda_client.get_all_tasks()
    coda_rows = coda_client.get_tt_data_rows()

    updates = 0
    for tt_key, row in coda_rows.items():
        vals = row["values"]
        task_tag = vals.get(config.TT_DATA_COLS["task_id"], "")
        if isinstance(task_tag, list):
            task_tag = task_tag[0] if task_tag else ""

        if not task_tag or not task_tag.startswith("#tsk-"):
            continue

        # Find the matching task
        tsk_id = task_tag.replace("#", "").upper()  # e.g., TSK-213
        task = tasks.get(tsk_id)
        if not task:
            continue

        # Check if task's project/WO changed vs what's in the TT data row
        current_proj = vals.get(config.TT_DATA_COLS["project_id"], "")
        current_wo = vals.get(config.TT_DATA_COLS["work_order_id"], "")
        if isinstance(current_proj, list):
            current_proj = current_proj[0] if current_proj else ""
        if isinstance(current_wo, list):
            current_wo = current_wo[0] if current_wo else ""

        # Task's tt_description field has the canonical tags
        task_tt_desc = task.get("name", "")  # This is the task name
        # We need to derive expected tags from the task's project/WO
        # The task row has project and work_order as lookup values (names, not IDs)
        # We can't easily reverse-map names to #pro-XX here, so we rely on
        # the tt_description field in All Tasks which contains the full tag string
        # For now, skip this phase — it will be handled when we have project ID lookups

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
