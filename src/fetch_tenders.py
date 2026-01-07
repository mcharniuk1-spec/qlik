import os
import json
from pathlib import Path
from src.utils import get_json, sleep_soft

"""
Incremental fetcher for OpenProcurement public API.

- Streams tender IDs from /tenders
- For each tender ID loads full tender /tenders/{id}
- Appends tender JSON into data/tenders_raw.jsonl
- Stores cursor-like offset in data/state.json
"""

BASE = os.getenv("OP_API_BASE", "https://public.api.openprocurement.org/api/2.5")

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "state.json"
OUT_JSONL = DATA_DIR / "tenders_raw.jsonl"

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"offset": None}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def stream_tender_index(offset: str | None = None, limit: int = 200):
    """
    Iterates over tender index and yields dicts: {id, dateModified, ...}
    """
    params = {"limit": limit}
    if offset:
        params["offset"] = offset

    while True:
        js = get_json(f"{BASE}/tenders", params=params)
        rows = js.get("data", [])
        if not rows:
            break

        for row in rows:
            yield row

        next_page = js.get("next_page") or {}
        next_offset = next_page.get("offset")
        if not next_offset:
            break

        params["offset"] = next_offset
        sleep_soft(0.05)

def fetch_full_tenders(max_docs: int | None = None) -> int:
    """
    Fetches tenders incrementally. If max_docs is set, stops after that many tenders.
    Returns number of tenders appended to jsonl.
    """
    state = load_state()
    offset = state.get("offset")

    count = 0
    with OUT_JSONL.open("a", encoding="utf-8") as f:
        for row in stream_tender_index(offset=offset, limit=200):
            tid = row.get("id")
            if not tid:
                continue

            full = get_json(f"{BASE}/tenders/{tid}")
            tender = full.get("data", {})
            f.write(json.dumps(tender, ensure_ascii=False) + "\n")
            count += 1

            # We store best-known offset; API typically uses dateModified-based offsets.
            state["offset"] = row.get("dateModified") or state.get("offset")

            if count % 200 == 0:
                save_state(state)

            if max_docs is not None and count >= max_docs:
                break

    save_state(state)
    return count

if __name__ == "__main__":
    max_docs_env = os.getenv("MAX_DOCS")
    max_docs = int(max_docs_env) if max_docs_env else None
    n = fetch_full_tenders(max_docs=max_docs)
    print(f"Fetched {n} tenders. Offset now: {load_state().get('offset')}")
