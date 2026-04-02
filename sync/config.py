import os
import re

# --- Credentials (from .env or environment) ---
TIMETAGGER_URL = os.environ.get("TIMETAGGER_URL", "").rstrip("/")
TIMETAGGER_API_TOKEN = os.environ.get("TIMETAGGER_API_TOKEN", "")
CF_ACCESS_CLIENT_ID = os.environ.get("CF_ACCESS_CLIENT_ID", "")
CF_ACCESS_CLIENT_SECRET = os.environ.get("CF_ACCESS_CLIENT_SECRET", "")
CODA_API_TOKEN = os.environ.get("CODA_API_TOKEN", "")

# --- Coda IDs ---
CODA_DOC_ID = "OSAZiA68PX"
CODA_TT_DATA_TABLE = "grid-9FUJAxlzM1"
CODA_ALL_TASKS_TABLE = "grid-L6CM1HyWMk"
CODA_PROJECTS_TABLE = "grid-Xvp3xIJw15"
CODA_WORK_ORDERS_TABLE = "grid-0Xxvqy_u70"

# --- Coda TimeTagger Data column IDs ---
TT_DATA_COLS = {
    "key": "c-glgKOl-WW9",
    "t1": "c-P9WLZzi9xn",
    "t2": "c-PQvnU9MExs",
    "ds": "c-m32qQSTKZr",
    "mt": "c-qz22T3LISp",
    "st": "c-o_Ak31GHu-",
    "task_id": "c-ebQbMruhu_",
    "project_id": "c-kzAsNv6GkK",
    "work_order_id": "c-tOvAoAHML6",
    "client_tag": "c-G18_5QZdYy",
    "ds_clean": "c-yP0UMcGSaA",
    "minutes": "c-aASCGCn0F_",
    "task_link": "c-Y7LTNta56C",
}

# --- Coda All Tasks column IDs ---
TASK_COLS = {
    "name": "c-kYQU7nZVNj",
    "status": "c-XH8JS9uHKm",
    "task_id": "c-Fb6N3kMNW3",
    "project": "c-q3fiT312d6",
    "client": "c-1qGOTwGZeU",
    "work_order": "c-dJl_t7828e",
    "tt_description": "c-MwasSqxwCF",
}

# --- Sync settings ---
SYNC_INTERVAL_SEC = 60
STATE_FILE = os.environ.get("SYNC_STATE_FILE", "/data/sync_state.json")

# --- Tag parsing ---
TAG_PATTERN = re.compile(r"#(tsk-\d+|pro-\d+|wo-\d+|nsight|personal|stinson|unassigned)")

def parse_tags(ds):
    """Extract tags from a TimeTagger description string."""
    tags = TAG_PATTERN.findall(ds or "")
    result = {"task_id": "", "project_id": "", "work_order_id": "", "client_tag": ""}
    for tag in tags:
        if tag.startswith("tsk-"):
            result["task_id"] = f"#{tag}"
        elif tag.startswith("pro-"):
            result["project_id"] = f"#{tag}"
        elif tag.startswith("wo-"):
            result["work_order_id"] = f"#{tag}"
        elif tag in ("nsight", "personal", "stinson"):
            result["client_tag"] = f"#{tag}"
        elif tag == "unassigned":
            pass  # skip
    return result

def clean_description(ds):
    """Remove all tags from a description."""
    return re.sub(r"\s*#\S+", "", ds or "").strip()

def rebuild_description(ds_clean, task_id, project_id, work_order_id, client_tag):
    """Rebuild a tagged description from clean text + tag components."""
    parts = [ds_clean]
    for tag in [task_id, project_id, work_order_id, client_tag]:
        if tag:
            parts.append(tag)
    return " ".join(parts)
