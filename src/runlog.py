import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunLog:
    jsonl_path: str
    events_list: List[Dict[str, Any]] = field(default_factory=list)

    def event(self, stage: str, **kwargs: Any) -> None:
        rec = {"ts": now_iso(), "stage": stage, **kwargs}
        self.events_list.append(rec)

    def flush(self) -> None:
        if not self.jsonl_path:
            return
        os.makedirs(os.path.dirname(self.jsonl_path), exist_ok=True)
        with open(self.jsonl_path, "w", encoding="utf-8") as f:
            for e in self.events_list:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")


def log_df_to_sheet(xw: pd.ExcelWriter, log: RunLog) -> None:
    df = pd.DataFrame(log.events_list)
    if df.empty:
        df = pd.DataFrame([{"ts": now_iso(), "stage": "no_logs"}])
    df.to_excel(xw, sheet_name="logs", index=False)
