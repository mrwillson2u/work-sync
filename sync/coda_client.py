import logging
import time
import requests
from config import (
    CODA_API_TOKEN, CODA_DOC_ID,
    CODA_TT_DATA_TABLE, CODA_ALL_TASKS_TABLE,
    TT_DATA_COLS, TASK_COLS,
)

log = logging.getLogger(__name__)
BASE = "https://coda.io/apis/v1"
RATE_DELAY = 2.5  # seconds between write requests


def _headers():
    return {"Authorization": f"Bearer {CODA_API_TOKEN}"}


def _get_all_rows(table_id):
    """Fetch all rows from a Coda table, handling pagination."""
    rows = []
    url = f"{BASE}/docs/{CODA_DOC_ID}/tables/{table_id}/rows?limit=500&valueFormat=simpleWithArrays"
    while url:
        resp = requests.get(url, headers=_headers(), timeout=60)
        resp.raise_for_status()
        data = resp.json()
        rows.extend(data.get("items", []))
        url = data.get("nextPageLink")
    return rows


# --- TimeTagger Data table operations ---

def get_tt_data_rows():
    """Get all rows from TimeTagger Data table, keyed by TT record key."""
    rows = _get_all_rows(CODA_TT_DATA_TABLE)
    keyed = {}
    for row in rows:
        vals = row.get("values", {})
        tt_key = vals.get(TT_DATA_COLS["key"], "")
        if tt_key:
            keyed[tt_key] = {
                "row_id": row["id"],
                "updated_at": row.get("updatedAt", ""),
                "values": vals,
            }
    log.info("Loaded %d TimeTagger Data rows from Coda", len(keyed))
    return keyed


def upsert_tt_data_row(tt_record, parsed_tags, existing_row_id=None, write_tags=True):
    """Insert or update a row in the TimeTagger Data table."""
    ds = tt_record.get("ds", "")
    t1 = tt_record.get("t1", 0)
    t2 = tt_record.get("t2", 0)

    cells = [
        {"column": TT_DATA_COLS["key"], "value": tt_record.get("key", "")},
        {"column": TT_DATA_COLS["t1"], "value": t1},
        {"column": TT_DATA_COLS["t2"], "value": t2},
        {"column": TT_DATA_COLS["ds"], "value": ds},
        {"column": TT_DATA_COLS["mt"], "value": tt_record.get("mt", 0)},
        {"column": TT_DATA_COLS["st"], "value": tt_record.get("st", 0)},
    ]

    if write_tags:
        cells.extend([
            {"column": TT_DATA_COLS["task_id"], "value": parsed_tags.get("task_id", "")},
            {"column": TT_DATA_COLS["project_id"], "value": parsed_tags.get("project_id", "")},
            {"column": TT_DATA_COLS["work_order_id"], "value": parsed_tags.get("work_order_id", "")},
            {"column": TT_DATA_COLS["client_tag"], "value": parsed_tags.get("client_tag", "")},
        ])

    if existing_row_id:
        url = f"{BASE}/docs/{CODA_DOC_ID}/tables/{CODA_TT_DATA_TABLE}/rows/{existing_row_id}"
        resp = requests.put(
            url, headers={**_headers(), "Content-Type": "application/json"},
            json={"row": {"cells": cells}},
            timeout=30,
        )
    else:
        url = f"{BASE}/docs/{CODA_DOC_ID}/tables/{CODA_TT_DATA_TABLE}/rows"
        resp = requests.post(
            url, headers={**_headers(), "Content-Type": "application/json"},
            json={"rows": [{"cells": cells}]},
            timeout=30,
        )

    if resp.status_code == 429:
        log.warning("Coda rate limited, waiting 30s...")
        time.sleep(30)
        # Retry with fresh request
        if existing_row_id:
            resp = requests.put(
                url, headers={**_headers(), "Content-Type": "application/json"},
                json={"row": {"cells": cells}}, timeout=30,
            )
        else:
            resp = requests.post(
                url, headers={**_headers(), "Content-Type": "application/json"},
                json={"rows": [{"cells": cells}]}, timeout=30,
            )

    if resp.status_code >= 400:
        log.error("Coda error %d: %s", resp.status_code, resp.text[:200])
    resp.raise_for_status()
    time.sleep(RATE_DELAY)
    return resp.json()


def update_tt_data_tags(row_id, task_tag, project_tag, wo_tag, client_tag, new_ds):
    """Update tag fields and ds on a TimeTagger Data row (after Coda→TT push confirms)."""
    cells = [
        {"column": TT_DATA_COLS["task_id"], "value": task_tag},
        {"column": TT_DATA_COLS["project_id"], "value": project_tag},
        {"column": TT_DATA_COLS["work_order_id"], "value": wo_tag},
        {"column": TT_DATA_COLS["client_tag"], "value": client_tag},
        {"column": TT_DATA_COLS["ds"], "value": new_ds},
    ]
    url = f"{BASE}/docs/{CODA_DOC_ID}/tables/{CODA_TT_DATA_TABLE}/rows/{row_id}"
    resp = requests.put(
        url, headers={**_headers(), "Content-Type": "application/json"},
        json={"row": {"cells": cells}},
        timeout=30,
    )
    resp.raise_for_status()
    time.sleep(RATE_DELAY)


# --- All Tasks table operations ---

def get_all_tasks():
    """Get all tasks, keyed by Task ID (e.g., 'TSK-213')."""
    rows = _get_all_rows(CODA_ALL_TASKS_TABLE)
    tasks = {}
    for row in rows:
        vals = row.get("values", {})
        tid = vals.get(TASK_COLS["task_id"], "")
        if tid:
            tasks[tid] = {
                "row_id": row["id"],
                "updated_at": row.get("updatedAt", ""),
                "name": vals.get(TASK_COLS["name"], ""),
                "project": vals.get(TASK_COLS["project"], ""),
                "work_order": vals.get(TASK_COLS["work_order"], ""),
                "client": vals.get(TASK_COLS["client"], ""),
            }
    log.info("Loaded %d tasks from Coda", len(tasks))
    return tasks


def _clean_ds(ds):
    import re
    return re.sub(r"\s*#\S+", "", ds or "").strip()
