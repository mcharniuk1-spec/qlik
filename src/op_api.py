import asyncio
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class OPHTTPError(RuntimeError):
    pass

def _url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")

@retry(
    reraise=True,
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError, OPHTTPError)),
)
async def _get_json(session: aiohttp.ClientSession, url: str, params: dict | None = None) -> dict:
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=50)) as resp:
        if resp.status in (429, 500, 502, 503, 504):
            raise OPHTTPError(f"Retryable HTTP {resp.status} for {url}")
        if resp.status != 200:
            txt = await resp.text()
            raise OPHTTPError(f"HTTP {resp.status} for {url}: {txt[:300]}")
        return await resp.json()

async def list_tenders(
    session: aiohttp.ClientSession,
    base: str,
    offset: str | None,
    limit: int
) -> tuple[list[dict], str | None]:
    url = _url(base, "/tenders")
    params: dict = {"limit": limit}

    if offset:
        params["offset"] = offset

    payload = await _get_json(session, url, params=params)
    data = payload.get("data", []) or []
    next_page = payload.get("next_page") or {}
    next_offset = next_page.get("offset") or None

    return data, next_offset

async def get_tender(session: aiohttp.ClientSession, base: str, tender_id: str) -> dict:
    url = _url(base, f"/tenders/{tender_id}")
    payload = await _get_json(session, url)
    return payload.get("data") or {}
