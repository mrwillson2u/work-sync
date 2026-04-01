import json
import logging
import requests
from config import (
    TIMETAGGER_URL, TIMETAGGER_API_TOKEN,
    CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET,
)

log = logging.getLogger(__name__)


def _headers():
    h = {
        "User-Agent": "tt-coda-sync/1.0",
        "authtoken": TIMETAGGER_API_TOKEN,
    }
    if CF_ACCESS_CLIENT_ID:
        h["CF-Access-Client-Id"] = CF_ACCESS_CLIENT_ID
    if CF_ACCESS_CLIENT_SECRET:
        h["CF-Access-Client-Secret"] = CF_ACCESS_CLIENT_SECRET
    return h


def get_records(start_epoch, end_epoch):
    """Fetch all TT records in a time range."""
    url = f"{TIMETAGGER_URL}/api/v2/records?timerange={start_epoch}-{end_epoch}"
    resp = requests.get(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json().get("records", [])


def get_updates(since_epoch):
    """Fetch TT records modified since a given epoch (for incremental sync)."""
    url = f"{TIMETAGGER_URL}/api/v2/updates?since={since_epoch}"
    resp = requests.get(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("records", [])


def put_records(records):
    """Upsert records into TimeTagger. Accepts a list of record dicts."""
    if not records:
        return {"accepted": [], "failed": [], "errors": []}
    url = f"{TIMETAGGER_URL}/api/v2/records"
    resp = requests.put(
        url,
        headers={**_headers(), "Content-Type": "application/json"},
        json=records,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("failed"):
        log.warning("TT put_records failures: %s", result["errors"])
    return result
