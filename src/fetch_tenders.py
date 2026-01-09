import asyncio
import os
from datetime import datetime, timezone
from time import monotonic

import aiohttp

from .config import Config, kyiv_epoch_for_year_start
from .logging_utils import setup_logger
from .op_api import list_tenders, get_tender
from .state import load_state, save_state
from .storage import connect, upsert_tender, upsert_item
from .milk_filter import is_milk_item

async def main_async() -> None:
    cfg = Config.load()
    logger = setup_logger("fetch", cfg.out_dir)

    os.makedirs(cfg.data_dir, exist_ok=True)

    st = load_state(cfg.state_path)

    # якщо перший запуск і offset нема — стартуємо з 2015-01-01 (Kyiv) як epoch
    if st.offset is None:
        st.offset = float(kyiv_epoch_for_year_start(2015))

    start = monotonic()
    deadline = start + cfg.max_runtime_seconds

    conn = connect(cfg.db_path)

    sem = asyncio.Semaphore(cfg.concurrency)
    fetched_at = datetime.now(timezone.utc).isoformat()

    async def fetch_one(tid: str) -> dict:
        async with sem:
            return await get_tender(session, cfg.op_api_base, tid)

    pages = 0
    while pages < cfg.max_pages and monotonic() < deadline:
        current_offset = st.offset

        data, next_offset = await list_tenders(session, cfg.op_api_base, current_offset, cfg.page_size)

        if not data:
            logger.info("No data returned — probably caught up. Stopping.")
            break

        if next_offset is None:
            logger.info("No next_page.offset — stopping.")
            break

        # safety breaker: avoid infinite loop
        if current_offset is not None and float(next_offset) == float(current_offset):
            logger.warning("next_offset == current_offset. Breaking to avoid infinite loop.")
            break

        tender_ids = [x.get("id") for x in data if x.get("id")]
        st.pages_done += 1
        st.tenders_scanned += len(tender_ids)

        # fetch tender details concurrently
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

            # upsert tender
            upsert_tender(conn, t, fetched_at)

            # upsert items
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

        # progress cursor — IMPORTANT: use next_page.offset
        st.offset = float(next_offset)
        save_state(cfg.state_path, st)

        pages += 1
        logger.info(
            f"Page {pages}/{cfg.max_pages} done | scanned={len(tender_ids)} "
            f"| milk_tenders={milk_tender_count} milk_items={milk_item_count} "
            f"| next_offset={st.offset}"
        )

    save_state(cfg.state_path, st)
    logger.info(
        f"Done. pages_done_total={st.pages_done} tenders_scanned_total={st.tenders_scanned} "
        f"milk_tenders_total={st.milk_tenders} milk_items_total={st.milk_items} offset={st.offset}"
    )

async def _runner() -> None:
    cfg = Config.load()
    headers = {"Accept": "application/json"}
    async with aiohttp.ClientSession(headers=headers) as session:
        globals()["session"] = session  # small hack to avoid threading session everywhere
        await main_async()

def main() -> None:
    asyncio.run(_runner())

if __name__ == "__main__":
    main()
