import logging
import time
import requests
from config import (
    CODA_API_TOKEN, CODA_DOC_ID,
    CODA_TT_DATA_TABLE, CODA_ALL_TASKS_TABLE,
    CODA_PROJECTS_TABLE, CODA_CLIENTS_TABLE,
    TT_DATA_COLS, TASK_COLS, PROJECT_COLS, CLIENT_COLS,
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


def upsert_tt_data_row(tt_record, parsed_tags, existing_row_id=None):
    """Insert or update a row in the TimeTagger Data table."""
    ds = tt_record.get("ds", "")
    t1 = tt_record.get("t1", 0)
    t2 = tt_record.get("t2", 0)

    # Only write core fields — tag columns are Coda formulas (auto-parsed from ds)
    cells = [
        {"column": TT_DATA_COLS["key"], "value": tt_record.get("key", "")},
        {"column": TT_DATA_COLS["t1"], "value": t1},
        {"column": TT_DATA_COLS["t2"], "value": t2},
        {"column": TT_DATA_COLS["ds"], "value": ds},
        {"column": TT_DATA_COLS["mt"], "value": tt_record.get("mt", 0)},
        {"column": TT_DATA_COLS["st"], "value": tt_record.get("st", 0)},
    ]

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
    """Update ds on a TimeTagger Data row. Tag columns are Coda formulas (auto-parsed from ds)."""
    cells = [
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


def get_clients():
    """Get all clients, keyed by display name. Returns short_name for use as tag."""
    rows = _get_all_rows(CODA_CLIENTS_TABLE)
    clients = {}
    for row in rows:
        vals = row.get("values", {})
        name = vals.get(CLIENT_COLS["name"], "")
        short = vals.get(CLIENT_COLS["short_name"], "")
        if name and short:
            clients[name] = f"#{short}"
    log.info("Loaded %d clients from Coda", len(clients))
    return clients


def get_projects(clients=None):
    """Get all projects, keyed by name. Resolves client name to tag via clients lookup."""
    if clients is None:
        clients = get_clients()
    rows = _get_all_rows(CODA_PROJECTS_TABLE)
    projects = {}
    for row in rows:
        vals = row.get("values", {})
        name = vals.get(PROJECT_COLS["name"], "")
        proj_id = vals.get(PROJECT_COLS["project_id"], "")
        wo = vals.get(PROJECT_COLS["work_order"], "")
        client_name = vals.get(PROJECT_COLS["client"], "")
        if name:
            projects[name] = {
                "project_id": f"#{proj_id.lower()}" if proj_id else "",
                "work_order_id": f"#{wo.lower()}" if wo else "",
                "client_tag": clients.get(client_name, ""),
            }
    log.info("Loaded %d projects from Coda", len(projects))
    return projects


def _clean_ds(ds):
    import re
    return re.sub(r"\s*#\S+", "", ds or "").strip()
