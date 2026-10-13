import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time
import zlib

import pyzipper
from pyzipper.zipfile_aes import AESZipInfo

from .logger import log_milestone
from .utils import format_size, format_speed

CHUNK_SIZE = 1024 * 1024


class ArchiveError(Exception):
  pass


class ArchivePasswordError(ArchiveError):
  pass


class ArchiveCorruptedError(ArchiveError):
  pass


class ArchiveWriteError(ArchiveError):
  pass


class ProgressReporter:
  def __init__(self, logger, label: str, total_bytes: int):
    self.logger = logger
    self.label = label
    self.total_bytes = total_bytes
    self.is_tty = sys.stdout.isatty()
    self.start_time = time.time()
    self.last_sample_time = self.start_time
    self.last_sample_bytes = 0
    self.last_speed_str = "0 B/s"
    self.last_percent = -1
    self.milestone_step = 50 * 1024 * 1024
    self.last_milestone = 0

  def update(self, processed: int):
    if self.total_bytes <= 0:
      return

    now = time.time()
    delta_time = now - self.last_sample_time
    if delta_time >= 0.5:
      speed = (processed - self.last_sample_bytes) / delta_time
      self.last_speed_str = format_speed(speed)
      self.last_sample_time = now
      self.last_sample_bytes = processed
    elif self.last_speed_str == "0 B/s":
      elapsed = now - self.start_time
      if elapsed > 0:
        self.last_speed_str = format_speed(processed / elapsed)
    speed_display = f" ({self.last_speed_str})"

    val = min(100, int(processed * 100 / self.total_bytes))
    if self.is_tty and val != self.last_percent:
      self.last_percent = val
      sys.stdout.write(f"\r{self.label}: {val}%{speed_display}\033[K")
      sys.stdout.flush()

    milestone = (processed // self.milestone_step) * self.milestone_step
    if milestone > 0 and milestone > self.last_milestone:
      self.last_milestone = milestone
      log_milestone(self.logger, f"{self.label}: {format_size(milestone)} ({val}%){speed_display}", self.is_tty)

  def finish(self):
    if self.is_tty and self.last_percent != -1:
      sys.stdout.write("\n")
      sys.stdout.flush()

    total_duration = time.time() - self.start_time
    avg_speed = self.total_bytes / total_duration if total_duration > 0 and self.total_bytes > 0 else 0
    final_speed_str = f" ({format_speed(avg_speed)})" if avg_speed > 0 else ""

    if self.total_bytes > 0 and self.last_milestone < self.total_bytes:
      log_milestone(self.logger, f"{self.label}: {format_size(self.total_bytes)} (100%){final_speed_str}", self.is_tty)
      self.last_milestone = self.total_bytes


def _zip_date_time(timestamp: float) -> tuple:
  date_time = time.localtime(timestamp)[0:6]
  if date_time[0] < 1980:
    return (1980, 1, 1, 0, 0, 0)
  if date_time[0] > 2107:
    return (2107, 12, 31, 23, 59, 59)
  return date_time


def _build_zip_info(arcname: str, st: os.stat_result) -> AESZipInfo:
  zinfo = AESZipInfo(arcname, _zip_date_time(st.st_mtime))
  zinfo.create_system = 3
  zinfo.external_attr = (st.st_mode & 0xFFFF) << 16
  return zinfo


def _collect_entries(source_dir: Path) -> tuple[list[tuple[Path, str]], int]:
  base = source_dir.parent
  entries = [(source_dir, source_dir.name)]
  total_bytes = 0

  for root, dirs, files in os.walk(source_dir, followlinks=False):
    root_path = Path(root)
    for name in sorted(dirs) + sorted(files):
      path = root_path / name
      arcname = path.relative_to(base).as_posix()
      entries.append((path, arcname))
      try:
        st = path.lstat()
        if stat.S_ISREG(st.st_mode):
          total_bytes += st.st_size
      except OSError:
        pass

  return entries, total_bytes


def create_encrypted_zip(source_dir: Path, archive_path: Path, password: str, logger) -> int:
  entries, total_bytes = _collect_entries(source_dir)
  reporter = ProgressReporter(logger, "Compressing snapshot", total_bytes)
  processed = 0

  with pyzipper.AESZipFile(
    archive_path,
    "w",
    compression=pyzipper.ZIP_DEFLATED,
    encryption=pyzipper.WZ_AES,
    allowZip64=True,
  ) as zf:
    zf.setpassword(password.encode("utf-8"))
    zf.setencryption(pyzipper.WZ_AES, nbits=256)

    for path, arcname in entries:
      try:
        st = path.lstat()
      except FileNotFoundError:
        continue

      if stat.S_ISLNK(st.st_mode):
        zinfo = _build_zip_info(arcname, st)
        zinfo.compress_type = pyzipper.ZIP_STORED
        zf.writestr(zinfo, os.readlink(path))
      elif stat.S_ISDIR(st.st_mode):
        zinfo = _build_zip_info(f"{arcname}/", st)
        zinfo.external_attr |= 0x10
        zinfo.compress_type = pyzipper.ZIP_STORED
        zf.writestr(zinfo, b"")
      elif stat.S_ISREG(st.st_mode):
        zinfo = _build_zip_info(arcname, st)
        zinfo.compress_type = pyzipper.ZIP_DEFLATED
        zinfo.file_size = st.st_size
        with open(path, "rb") as src, zf.open(zinfo, "w", force_zip64=True) as dst:
          while chunk := src.read(CHUNK_SIZE):
            dst.write(chunk)
            processed += len(chunk)
            reporter.update(processed)

  reporter.finish()
  return total_bytes


def _safe_target(recovery_dir: Path, name: str) -> Path | None:
  parts = [p for p in PurePosixPath(name.replace("\\", "/")).parts if p not in ("", ".", "/")]
  if not parts or any(p == ".." for p in parts):
    return None
  target = recovery_dir.joinpath(*parts)
  try:
    target.resolve(strict=False).relative_to(recovery_dir.resolve())
  except ValueError:
    return None
  return target


def _remove_existing(target: Path):
  if target.is_symlink() or target.is_file():
    target.unlink()


def _apply_metadata(target: Path, info: pyzipper.ZipInfo):
  mode = (info.external_attr >> 16) & 0o7777
  try:
    if mode:
      os.chmod(target, mode)
    mtime = time.mktime(info.date_time + (0, 0, -1))
    os.utime(target, (mtime, mtime))
  except (OSError, OverflowError, ValueError):
    pass


def extract_encrypted_zip(archive_path: Path, recovery_dir: Path, password: str, logger):
  recovery_dir.mkdir(parents=True, exist_ok=True)

  try:
    with pyzipper.AESZipFile(archive_path, "r") as zf:
      zf.setpassword(password.encode("utf-8"))
      infos = zf.infolist()
      total_bytes = sum(i.file_size for i in infos if not i.is_dir())
      reporter = ProgressReporter(logger, "Extracting snapshot", total_bytes)
      processed = 0
      directories = []

      for info in infos:
        target = _safe_target(recovery_dir, info.filename)
        if target is None:
          logger.warning("Skipping unsafe archive entry: %s", info.filename)
          continue

        file_mode = info.external_attr >> 16

        if info.is_dir():
          target.mkdir(parents=True, exist_ok=True)
          directories.append((target, info))
          continue

        target.parent.mkdir(parents=True, exist_ok=True)

        if stat.S_ISLNK(file_mode):
          link_target = zf.read(info).decode("utf-8")
          _remove_existing(target)
          os.symlink(link_target, target)
          processed += info.file_size
          reporter.update(processed)
          continue

        _remove_existing(target)
        with zf.open(info, "r") as src, open(target, "wb") as dst:
          while chunk := src.read(CHUNK_SIZE):
            dst.write(chunk)
            processed += len(chunk)
            reporter.update(processed)
        _apply_metadata(target, info)

      for target, info in reversed(directories):
        _apply_metadata(target, info)

      reporter.finish()
  except RuntimeError as err:
    if "password" in str(err).lower():
      raise ArchivePasswordError(str(err)) from err
    raise ArchiveError(str(err)) from err
  except (pyzipper.BadZipFile, zlib.error, EOFError) as err:
    raise ArchiveCorruptedError(str(err)) from err
  except OSError as err:
    raise ArchiveWriteError(str(err)) from err
