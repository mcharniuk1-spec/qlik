import os
from dataclasses import dataclass

def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default

def _parse_csv(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]

def _parse_bool(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "y", "on")

@dataclass(frozen=True)
class Config:
    op_api_base: str
    data_dir: str
    out_dir: str

    log_dir: str
    keep_log_files: int

    max_pages: int
    max_runtime_seconds: int
    page_size: int
    concurrency: int

    start_offset: str
    reset_state: bool
    reset_db: bool

    milk_cpv_prefixes: list[str]
    milk_keywords: list[str]

    state_path: str
    db_path: str

    @staticmethod
    def load() -> "Config":
        data_dir = _env("DATA_DIR", "data")
        out_dir = _env("OUT_DIR", "out")
        log_dir = _env("LOG_DIR", os.path.join(out_dir, "logs"))

        start_offset = _env("START_OFFSET", "").strip()

        return Config(
            op_api_base=_env("OP_API_BASE", "https://public.api.openprocurement.org/api/2.5"),
            data_dir=data_dir,
            out_dir=out_dir,

            log_dir=log_dir,
            keep_log_files=int(_env("KEEP_LOG_FILES", "15")),

            max_pages=int(_env("MAX_PAGES", "25")),
            max_runtime_seconds=int(_env("MAX_RUNTIME_SECONDS", "2400")),
            page_size=int(_env("PAGE_SIZE", "100")),
            concurrency=int(_env("CONCURRENCY", "12")),

            start_offset=start_offset,
            reset_state=_parse_bool(_env("RESET_STATE", "false")),
            reset_db=_parse_bool(_env("RESET_DB", "false")),

            milk_cpv_prefixes=_parse_csv(_env("MILK_CPV_PREFIXES", "1551")),
            milk_keywords=[k.lower() for k in _parse_csv(_env("MILK_KEYWORDS", "молоко,milk"))],

            state_path=os.path.join(data_dir, "state.json"),
            db_path=os.path.join(data_dir, "prozorro_milk.sqlite"),
        )
