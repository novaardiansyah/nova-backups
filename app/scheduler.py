import os
import signal
import threading

from .backup import run_backup
from .logger import setup_logger
from .utils import BackupLock


def parse_interval(interval_str: str | None, default: int = 60) -> int:
    if not interval_str:
        return default
    clean_str = str(interval_str).strip().lower()
    if clean_str.endswith("s"):
        val = clean_str[:-1].strip()
        return int(val) if val.isdigit() else default
    if clean_str.endswith("m"):
        val = clean_str[:-1].strip()
        return int(val) * 60 if val.isdigit() else default
    if clean_str.endswith("h"):
        val = clean_str[:-1].strip()
        return int(val) * 3600 if val.isdigit() else default
    if clean_str.endswith("d"):
        val = clean_str[:-1].strip()
        return int(val) * 86400 if val.isdigit() else default
    if clean_str.isdigit():
        return int(clean_str)
    return default


def run_scheduler(logger=None):
    if logger is None:
        logger = setup_logger()

    interval_raw = os.environ.get("BACKUP_INTERVAL") or "60"
    interval_seconds = max(1, parse_interval(interval_raw, default=60))

    logger.info("Starting Backup Scheduler (Interval: %s seconds / %s)...", interval_seconds, interval_raw)

    stop_event = threading.Event()

    def signal_handler(signum, frame):
        logger.info("Received termination signal (%s). Shutting down scheduler...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        run_backup({}, logger)
    except Exception as err:
        logger.error("Initial backup run encountered error: %s", err)

    while not stop_event.is_set():
        if stop_event.wait(timeout=interval_seconds):
            break
        try:
            run_backup({}, logger)
        except Exception as err:
            logger.error("Scheduled backup run encountered error: %s", err)

    logger.info("Backup Scheduler stopped.")
