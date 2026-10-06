import hashlib
from pathlib import Path


def format_size(size_bytes: int | float) -> str:
    if size_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    val = float(size_bytes)
    while val >= 1024 and unit_index < len(units) - 1:
        val /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(val)} B"
    formatted = f"{val:.2f}"
    if formatted.endswith(".00"):
        return f"{int(val)} {units[unit_index]}"
    if formatted.endswith("0"):
        return f"{val:.1f} {units[unit_index]}"
    return f"{formatted} {units[unit_index]}"


def format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec <= 0:
        return "0 B/s"
    return f"{format_size(bytes_per_sec)}/s"


def calculate_checksum(file_path: Path) -> str | None:
    try:
        if not file_path.exists() or not file_path.is_file():
            return None
        sha256 = hashlib.sha256()
        with file_path.open("rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        return sha256.hexdigest()
    except OSError:
        return None


class BackupLock:
    def __init__(self, lock_file: Path = Path("/tmp/nova_backup.lock")):
        self.lock_file = lock_file
        self._fd = None

    def acquire(self) -> bool:
        import fcntl
        import os

        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self._fd = open(self.lock_file, "w")
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fd.write(f"{os.getpid()}\n")
            self._fd.flush()
            return True
        except (BlockingIOError, OSError):
            if self._fd:
                try:
                    self._fd.close()
                except Exception:
                    pass
                self._fd = None
            return False

    def release(self):
        import fcntl

        if self._fd:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                self._fd.close()
            except Exception:
                pass
            self._fd = None


def cleanup_empty_directories(target_dir: Path, stop_at: Path | None = None):
    if stop_at is None:
        stop_at = Path("/backup")
    try:
        stop_resolved = stop_at.resolve()
        current = target_dir.resolve()
        while current and current != stop_resolved:
            try:
                if not current.is_relative_to(stop_resolved):
                    break
            except AttributeError:
                pass
            if current.exists() and current.is_dir():
                if not any(current.iterdir()):
                    current.rmdir()
                else:
                    break
            else:
                break
            current = current.parent
    except Exception:
        pass
