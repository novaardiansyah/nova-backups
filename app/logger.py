from datetime import datetime
import logging
import os
from pathlib import Path
import re
import subprocess


def set_global_permissions(target: Path):
    target_uid = 0
    target_gid = 0

    log_dir = Path("/app/logs")
    backup_path = Path("/backup")

    if log_dir.exists() and log_dir.stat().st_uid != 0:
        target_uid = log_dir.stat().st_uid
        target_gid = log_dir.stat().st_gid
    elif backup_path.exists() and backup_path.stat().st_uid != 0:
        target_uid = backup_path.stat().st_uid
        target_gid = backup_path.stat().st_gid

    if target_uid != 0:
        subprocess.run(
            ["chown", "-R", f"{target_uid}:{target_gid}", str(target)],
            check=False,
        )

    subprocess.run(
        ["chmod", "-R", "777", str(target)],
        check=False,
    )

    try:
        os.chmod(target, 0o777)
        if target.is_dir():
            for root, dirs, files in os.walk(target):
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root, d), 0o777)
                    except OSError:
                        pass
                for f in files:
                    try:
                        os.chmod(os.path.join(root, f), 0o777)
                    except OSError:
                        pass
    except Exception:
        pass


class DailyRotatingFileHandler(logging.FileHandler):
    def __init__(
        self,
        log_dir: Path,
        max_files: int = 7,
        max_bytes: int = 2 * 1024 * 1024,
        encoding: str = "utf-8",
    ):
        self.log_dir = log_dir
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.log_dir.mkdir(parents=True, exist_ok=True)
        set_global_permissions(self.log_dir)

        old_backup_log = self.log_dir / "backup.log"
        if old_backup_log.exists():
            mtime_str = datetime.fromtimestamp(old_backup_log.stat().st_mtime).strftime("%Y%m%d")
            migrated = self.log_dir / f"backup-{mtime_str}-1.log"
            if not migrated.exists():
                try:
                    old_backup_log.rename(migrated)
                except OSError:
                    pass

        for old_file in self.log_dir.glob("backup-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].log"):
            if old_file.is_file():
                stem = old_file.stem
                date_str = stem.replace("backup-", "")
                migrated = self.log_dir / f"backup-{date_str}-1.log"
                if not migrated.exists():
                    try:
                        old_file.rename(migrated)
                    except OSError:
                        pass

        self.current_date = datetime.now().strftime("%Y%m%d")
        self.current_index = self._get_active_index_for_date(self.current_date)
        log_path = self._get_log_path(self.current_date, self.current_index)
        super().__init__(str(log_path.resolve()), encoding=encoding)
        set_global_permissions(self.log_dir)
        self.prune_old_logs()

    def _open(self):
        stream = super()._open()
        try:
            set_global_permissions(Path(self.baseFilename))
        except Exception:
            pass
        return stream

    def _get_log_path(self, date_str: str, index: int) -> Path:
        return self.log_dir / f"backup-{date_str}-{index}.log"

    def _get_active_index_for_date(self, date_str: str) -> int:
        indices = []
        pattern = re.compile(rf"^backup-{re.escape(date_str)}-(\d+)\.log$")
        for f in self.log_dir.glob(f"backup-{date_str}-*.log"):
            if not f.is_file():
                continue
            m = pattern.match(f.name)
            if m:
                indices.append(int(m.group(1)))

        if not indices:
            return 1

        max_index = max(indices)
        target_file = self._get_log_path(date_str, max_index)
        try:
            if target_file.exists() and target_file.stat().st_size >= self.max_bytes:
                return max_index + 1
        except OSError:
            pass

        return max_index

    def should_rollover(self, record) -> bool:
        if self.max_bytes <= 0:
            return False
        msg = f"{self.format(record)}\n"
        msg_bytes = len(msg.encode(self.encoding or "utf-8"))
        try:
            if self.stream is None:
                self.stream = self._open()
            self.stream.seek(0, 2)
            current_size = self.stream.tell()
        except (OSError, ValueError):
            try:
                log_file = Path(self.baseFilename)
                current_size = log_file.stat().st_size if log_file.exists() else 0
            except OSError:
                current_size = 0

        if current_size >= self.max_bytes or (current_size > 0 and current_size + msg_bytes >= self.max_bytes):
            return True
        return False

    def do_rollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        self.current_index += 1
        log_path = self._get_log_path(self.current_date, self.current_index)
        while log_path.exists() and log_path.stat().st_size >= self.max_bytes:
            self.current_index += 1
            log_path = self._get_log_path(self.current_date, self.current_index)
        self.baseFilename = str(log_path.resolve())
        self.stream = self._open()
        set_global_permissions(self.log_dir)
        self.prune_old_logs()

    def prune_old_logs(self):
        try:
            date_groups = {}
            pattern = re.compile(r"^backup-(\d{8})(?:-(\d+))?\.log$")
            for f in self.log_dir.glob("backup-*.log"):
                if not f.is_file():
                    continue
                m = pattern.match(f.name)
                if m:
                    d = m.group(1)
                    date_groups.setdefault(d, []).append(f)

            sorted_dates = sorted(date_groups.keys())
            if len(sorted_dates) > self.max_files:
                for old_date in sorted_dates[:-self.max_files]:
                    for old_file in date_groups[old_date]:
                        try:
                            old_file.unlink(missing_ok=True)
                        except OSError:
                            pass
        except Exception:
            pass

    def emit(self, record):
        try:
            today = datetime.now().strftime("%Y%m%d")
            if today != self.current_date:
                if self.stream:
                    self.stream.close()
                    self.stream = None
                self.current_date = today
                self.current_index = self._get_active_index_for_date(today)
                self.baseFilename = str(self._get_log_path(self.current_date, self.current_index).resolve())
                self.stream = self._open()
                set_global_permissions(self.log_dir)
                self.prune_old_logs()
            elif self.should_rollover(record):
                self.do_rollover()
            super().emit(record)
        except Exception:
            self.handleError(record)


def get_log_dir() -> Path:
    log_dir = Path("/app/logs")
    if not log_dir.exists():
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log_dir = Path("./logs")
            log_dir.mkdir(parents=True, exist_ok=True)
    set_global_permissions(log_dir)
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
        max_bytes=2 * 1024 * 1024,
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

