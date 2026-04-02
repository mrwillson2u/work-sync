"""Bootstrap for agent tools: loads .env and sets up import paths."""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env():
    """Load .env file into os.environ (simple key=value parser)."""
    env_path = os.path.join(REPO_ROOT, ".env")
    if not os.path.exists(env_path):
        print(f"ERROR: .env file not found at {env_path}", file=sys.stderr)
        sys.exit(1)
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                os.environ.setdefault(key, value)


def init():
    """Initialize environment and import paths. Call this before any sync/ imports."""
    _load_env()
    sync_path = os.path.join(REPO_ROOT, "sync")
    if sync_path not in sys.path:
        sys.path.insert(0, sync_path)
