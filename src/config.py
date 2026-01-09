import os
from dataclasses import dataclass
from datetime import datetime, timezone
from dateutil import tz

def _env(name: str, default: str) -> str:
    val = os.getenv(name)
    return val if val is not None and val != "" else default

def _parse_csv(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]

def kyiv_epoch_for_year_start(year: int) -> float:
    kyiv = tz.gettz("Europe/Kyiv")
    dt = datetime(year, 1, 1, 0, 0, 0, tzinfo=kyiv)
    return dt.astimezone(timezone.utc).timestamp()

@dataclass(frozen=True)
class Config:
    op_api_base: str
    data_dir: str
    out_dir: str

    mode: str
    max_pages: int
    max_runtime_seconds: int
    page_size: int
    concurrency: int

    # milk filters
    milk_cpv_prefixes: list[str]
    milk_keywords: list[str]

    # persistence
    state_path: str
    db_path: str

    @staticmethod
    def load() -> "Config":
        data_dir = _env("DATA_DIR", "data")
        out_dir = _env("OUT_DIR", "out")

        max_pages = int(_env("MAX_PAGES", "25"))
        max_runtime_seconds = int(_env("MAX_RUNTIME_SECONDS", "2400"))
        page_size = int(_env("PAGE_SIZE", "100"))
        concurrency = int(_env("CONCURRENCY", "12"))

        return Config(
            op_api_base=_env("OP_API_BASE", "https://public.api.openprocurement.org/api/2.5"),
            data_dir=data_dir,
            out_dir=out_dir,
            mode=_env("MODE", "incremental").strip().lower(),
            max_pages=max_pages,
            max_runtime_seconds=max_runtime_seconds,
            page_size=page_size,
            concurrency=concurrency,
            milk_cpv_prefixes=_parse_csv(_env("MILK_CPV_PREFIXES", "1551")),
            milk_keywords=[k.lower() for k in _parse_csv(_env("MILK_KEYWORDS", "молоко,milk,uht,ультрапастер,пастер"))],
            state_path=os.path.join(data_dir, "state.json"),
            db_path=os.path.join(data_dir, "prozorro_milk.sqlite"),
        )
