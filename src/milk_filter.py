def _norm(s: str | None) -> str:
    return (s or "").strip().lower()

def is_milk_item(item: dict, cpv_prefixes: list[str], keywords: list[str]) -> bool:
    # CPV / DK021
    cl = item.get("classification") or {}
    cl_id = str(cl.get("id") or "").strip()
    if cl_id:
        for p in cpv_prefixes:
            if cl_id.startswith(p):
                return True

    # fallback: description keywords
    desc = _norm(item.get("description"))
    if desc:
        for k in keywords:
            if k and k in desc:
                return True

    return False
