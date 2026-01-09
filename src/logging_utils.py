import logging
import os
import glob
from datetime import datetime

def _rotate(prefix_glob: str, keep: int) -> None:
    files = sorted(glob.glob(prefix_glob))
    if len(files) <= keep:
        return
    to_delete = files[: max(0, len(files) - keep)]
    for p in to_delete:
        try:
            os.remove(p)
        except OSError:
            pass

def setup_stage_logger(stage: str, log_dir: str, keep_files: int = 15) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(f"stage:{stage}")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    latest_path = os.path.join(log_dir, f"{stage}_latest.log")
    hist_path = os.path.join(log_dir, f"{stage}_{ts}.log")

    fh_latest = logging.FileHandler(latest_path, mode="w", encoding="utf-8")
    fh_latest.setFormatter(fmt)
    logger.addHandler(fh_latest)

    fh_hist = logging.FileHandler(hist_path, mode="w", encoding="utf-8")
    fh_hist.setFormatter(fmt)
    logger.addHandler(fh_hist)

    _rotate(os.path.join(log_dir, f"{stage}_????????_??????.log"), keep_files)
    logger.info(f"Logging to: {latest_path} and {hist_path}")
    return logger
