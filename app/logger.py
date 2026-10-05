from datetime import datetime
import logging
from pathlib import Path


class DailyRotatingFileHandler(logging.FileHandler):
    def __init__(self, log_dir: Path, max_files: int = 7, encoding: str = "utf-8"):
        self.log_dir = log_dir
        self.max_files = max_files
        self.log_dir.mkdir(parents=True, exist_ok=True)
        old_backup_log = self.log_dir / "backup.log"
        if old_backup_log.exists():
            mtime_str = datetime.fromtimestamp(old_backup_log.stat().st_mtime).strftime("%Y%m%d")
            migrated = self.log_dir / f"backup-{mtime_str}.log"
            if not migrated.exists():
                try:
                    old_backup_log.rename(migrated)
                except OSError:
                    pass
        self.current_date = datetime.now().strftime("%Y%m%d")
        log_path = self.log_dir / f"backup-{self.current_date}.log"
        super().__init__(str(log_path), encoding=encoding)
        self.prune_old_logs()

    def prune_old_logs(self):
        try:
            log_files = sorted(
                [f for f in self.log_dir.glob("backup-*.log") if f.is_file()],
                key=lambda p: p.name,
            )
            if len(log_files) > self.max_files:
                for old_file in log_files[:-self.max_files]:
                    try:
                        old_file.unlink(missing_ok=True)
                    except OSError:
                        pass
        except Exception:
            pass

    def emit(self, record):
        today = datetime.now().strftime("%Y%m%d")
        if today != self.current_date:
            self.current_date = today
            self.close()
            self.baseFilename = str(self.log_dir / f"backup-{today}.log")
            self.stream = self._open()
            self.prune_old_logs()
        super().emit(record)


def get_log_dir() -> Path:
    log_dir = Path("/app/logs")
    if not log_dir.exists():
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log_dir = Path("./logs")
            log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logger():
    log_dir = get_log_dir()

    logger = logging.getLogger("nova-backup")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    file_handler = DailyRotatingFileHandler(
        log_dir,
        max_files=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def log_milestone(logger, message: str, is_tty: bool):
    if is_tty:
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                record = logger.makeRecord(
                    logger.name,
                    logging.INFO,
                    "",
                    0,
                    message,
                    (),
                    None,
                )
                handler.handle(record)
    else:
        logger.info(message)

