"""Data layer for agent tools. Pure data fetching and aggregation — no business logic."""

from collections import defaultdict

import requests

import config
import tt_client
import coda_client


# --- Generic Coda table fetcher ---

def fetch_table(table_id):
    """Fetch all rows from a Coda table using human-readable column names."""
    rows = []
    base = "https://coda.io/apis/v1"
    url = (
        f"{base}/docs/{config.CODA_DOC_ID}/tables/{table_id}/rows"
        f"?limit=500&valueFormat=simpleWithArrays&useColumnNames=true"
    )
    headers = {"Authorization": f"Bearer {config.CODA_API_TOKEN}"}
    while url:
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        rows.extend(data.get("items", []))
        url = data.get("nextPageLink")
    return [{"row_id": r["id"], **r.get("values", {})} for r in rows]


# --- Coda table accessors ---

def get_work_orders():
    """Fetch all work orders. Returns list of dicts with all Coda column values."""
    return fetch_table(config.CODA_WORK_ORDERS_TABLE)


def get_projects():
    """Fetch all projects. Returns list of dicts with all Coda column values."""
    return fetch_table(config.CODA_PROJECTS_TABLE)


def get_tasks():
    """Fetch all tasks. Returns list of dicts with task_id, name, project, etc."""
    raw = coda_client.get_all_tasks()
    return [
        {"task_id": tid, **info}
        for tid, info in raw.items()
    ]


# --- TimeTagger data ---

def get_tt_hours(start_epoch, end_epoch):
    """Fetch TT records with parsed tags and computed duration."""
    records = tt_client.get_records(int(start_epoch), int(end_epoch))
    result = []
    for rec in records:
        t1, t2 = rec.get("t1", 0), rec.get("t2", 0)
        tags = config.parse_tags(rec.get("ds", ""))
        result.append({
            "t1": t1,
            "t2": t2,
            "duration_hours": round((t2 - t1) / 3600.0, 2) if t2 > t1 else 0,
            "description": config.clean_description(rec.get("ds", "")),
            "tags": tags,
        })
    return result


def aggregate_hours(records, group_by="work_order_id"):
    """Aggregate TT record hours by a tag field. Returns {tag: total_hours}.

    group_by: 'work_order_id', 'project_id', 'task_id', or 'client_tag'
    """
    totals = defaultdict(float)
    for rec in records:
        key = rec["tags"].get(group_by) or "untagged"
        totals[key] += rec["duration_hours"]
    return {k: round(v, 2) for k, v in totals.items()}
