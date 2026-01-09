import asyncio
import os
import json
from datetime import datetime, timezone
from time import monotonic

import aiohttp

from .config import Config
from .logging_utils import setup_stage_logger
from .op_api import list_tenders, get_tender
from .state import State, load_state, save_state
from .storage import connect, upsert_tender, upsert_item
from .milk_filter import is_milk_item

def _reset_state_if_needed(cfg: Config, st: State, logger) -> State:
    if not cfg.reset_state:
        return st
    logger.warning("RESET_STATE=true -> resetting state to START_OFFSET (or None).")
    return State(
        offset=cfg.start_offset if cfg.start_offset else None,
        updated_at=None,
        pages_done=0,
        tenders_scanned=0,
        tenders_fetched=0,
        milk_tenders=0,
        milk_items=0,
    )

async def main_async() -> None:
    cfg = Config.load()
    logger = setup_stage_logger("fetch", cfg.log_dir, cfg.keep_log_files)

    os.makedirs(cfg.data_dir, exist_ok=True)
    os.makedirs(cfg.out_dir, exist_ok=True)
    report_dir = os.path.join(cfg.out_dir, "reports")
    os.makedirs(report_dir, exist_ok=True)

    st = load_state(cfg.state_path)
    st = _reset_state_if_needed(cfg, st, logger)

    if cfg.reset_db and os.path.exists(cfg.db_path):
        logger.warning("RESET_DB=true -> deleting SQLite database.")
        os.remove(cfg.db_path)

    conn = connect(cfg.db_path)

    if st.offset is None and cfg.start_offset:
        st.offset = cfg.start_offset

    start = monotonic()
    deadline = start + cfg.max_runtime_seconds

    sem = asyncio.Semaphore(cfg.concurrency)
    fetched_at = datetime.now(timezone.utc).isoformat()

    headers = {"Accept": "application/json"}
    async with aiohttp.ClientSession(headers=headers) as session:

        async def fetch_one(tid: str) -> dict:
            async with sem:
                return await get_tender(session, cfg.op_api_base, tid)

        pages = 0
        while pages < cfg.max_pages and monotonic() < deadline:
            current_offset = st.offset
            data, next_offset = await list_tenders(session, cfg.op_api_base, current_offset, cfg.page_size)

            if not data:
                logger.info("No data returned. Likely caught up. Stop.")
                break
            if not next_offset:
                logger.info("No next_page.offset. Stop.")
                break
            if current_offset is not None and next_offset == current_offset:
                logger.warning("next_offset == current_offset -> break to avoid infinite loop.")
                break

            tender_ids = [x.get("id") for x in data if x.get("id")]
            st.pages_done += 1
            st.tenders_scanned += len(tender_ids)

            tenders = await asyncio.gather(*[fetch_one(tid) for tid in tender_ids], return_exceptions=True)
            st.tenders_fetched += len(tender_ids)

            milk_tender_count = 0
            milk_item_count = 0

            for t in tenders:
                if isinstance(t, Exception):
                    logger.warning(f"Tender fetch failed: {t}")
                    continue

                items = t.get("items") or []
                milk_items = []
                for idx, it in enumerate(items):
                    if is_milk_item(it, cfg.milk_cpv_prefixes, cfg.milk_keywords):
                        milk_items.append((idx, it))

                if not milk_items:
                    continue

                milk_tender_count += 1
                upsert_tender(conn, t, fetched_at)

                for idx, it in milk_items:
                    item_id = it.get("id")
                    item_key = str(item_id) if item_id is not None else str(idx)

                    cl = it.get("classification") or {}
                    unit = it.get("unit") or {}
                    dd = it.get("deliveryDate") or {}
                    addr = it.get("deliveryAddress") or {}

                    row = {
                        "description": it.get("description"),
                        "classification_id": cl.get("id"),
                        "classification_scheme": cl.get("scheme"),
                        "quantity": it.get("quantity"),
                        "unit_name": unit.get("name"),
                        "unit_code": unit.get("code"),
                        "delivery_start": dd.get("startDate"),
                        "delivery_end": dd.get("endDate"),
                        "region": addr.get("region"),
                        "locality": addr.get("locality"),
                        "dateModified": t.get("dateModified"),
                    }
                    upsert_item(conn, t.get("id"), item_key, row)
                    milk_item_count += 1

            conn.commit()

            st.milk_tenders += milk_tender_count
            st.milk_items += milk_item_count

            # offset зберігаємо як рядок (курсором)
            st.offset = next_offset
            save_state(cfg.state_path, st)

            pages += 1
            logger.info(
                f"Page {pages}/{cfg.max_pages} | scanned={len(tender_ids)} "
                f"| milk_tenders={milk_tender_count} milk_items={milk_item_count} | next_offset={st.offset}"
            )

        save_state(cfg.state_path, st)

    elapsed = round(monotonic() - start, 3)
    report = {
        "status": "ok",
        "elapsed_seconds": elapsed,
        "state": st.__dict__,
        "api_base": cfg.op_api_base,
        "pagination": {"limit": cfg.page_size, "offset": st.offset},
    }
    with open(os.path.join(report_dir, "fetch_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

def main() -> None:
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
