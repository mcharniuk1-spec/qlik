import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass
class State:
    offset: float | None = None
    updated_at: str | None = None
    pages_done: int = 0
    tenders_scanned: int = 0
    tenders_fetched: int = 0
    milk_tenders: int = 0
    milk_items: int = 0

def load_state(path: str) -> State:
    if not os.path.exists(path):
        return State()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f) or {}
    return State(
        offset=raw.get("offset"),
        updated_at=raw.get("updated_at"),
        pages_done=int(raw.get("pages_done", 0)),
        tenders_scanned=int(raw.get("tenders_scanned", 0)),
        tenders_fetched=int(raw.get("tenders_fetched", 0)),
        milk_tenders=int(raw.get("milk_tenders", 0)),
        milk_items=int(raw.get("milk_items", 0)),
    )

def save_state(path: str, st: State) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    st.updated_at = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st.__dict__, f, ensure_ascii=False, indent=2)
