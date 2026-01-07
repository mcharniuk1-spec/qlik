import time
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "prozorro-milk-export/1.0 (+github-actions)"})

@retry(stop=stop_after_attempt(6), wait=wait_exponential(multiplier=1, min=1, max=30))
def get_json(url: str, params: dict | None = None, timeout: int = 60) -> dict:
    """
    Robust GET JSON with retries on transient failures.
    """
    r = SESSION.get(url, params=params, timeout=timeout)
    if r.status_code in (429, 500, 502, 503, 504):
        raise RuntimeError(f"Retryable HTTP {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    return r.json()

def sleep_soft(sec: float = 0.1) -> None:
    time.sleep(sec)
