import os
import re
from pathlib import Path
import stat
import subprocess
import sys
import time

import pyzipper
from pyzipper.zipfile_aes import AESZipInfo

from .logger import log_milestone
from .utils import format_size, format_speed, get_env_int

CHUNK_SIZE = 1024 * 1024


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
    self.last_processed = 0
    self.milestone_step = 50 * 1024 * 1024
    self.last_milestone = 0

  def update(self, processed: int):
    if self.total_bytes <= 0:
      return

    processed = max(processed, self.last_processed)
    self.last_processed = processed

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
    speed_display = f" at {self.last_speed_str}" if self.last_speed_str != "0 B/s" else ""

    val = min(99, int(processed * 100 / self.total_bytes))
    if self.is_tty and val != self.last_percent:
      self.last_percent = val
      sys.stdout.write(f"\r{self.label}: {format_size(processed)} / {format_size(self.total_bytes)} ({val}%){speed_display}\033[K")
      sys.stdout.flush()

    while self.last_milestone + self.milestone_step <= processed and self.last_milestone + self.milestone_step < self.total_bytes:
      self.last_milestone += self.milestone_step
      milestone_val = min(99, int(self.last_milestone * 100 / self.total_bytes))
      log_milestone(self.logger, f"{self.label}: {format_size(self.last_milestone)} / {format_size(self.total_bytes)} ({milestone_val}%){speed_display}", self.is_tty)

  def finish(self):
    if self.is_tty and self.last_percent != -1:
      sys.stdout.write("\n")
      sys.stdout.flush()

    total_duration = time.time() - self.start_time
    avg_speed = self.total_bytes / total_duration if total_duration > 0 and self.total_bytes > 0 else 0
    final_speed_str = f" at {format_speed(avg_speed)}" if avg_speed > 0 else ""

    if self.total_bytes <= 0:
      log_milestone(self.logger, f"{self.label}: 0 B / 0 B (100%){final_speed_str}", self.is_tty)
    elif self.last_milestone < self.total_bytes:
      log_milestone(self.logger, f"{self.label}: {format_size(self.total_bytes)} / {format_size(self.total_bytes)} (100%){final_speed_str}", self.is_tty)
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


def create_encrypted_rar(source_dir: Path, archive_path: Path, password: str, logger) -> int:
  rar_threads = max(1, get_env_int("RAR_THREADS", 1))
  archive_target = archive_path.name if archive_path.parent == source_dir.parent else str(archive_path.resolve())
  command = [
    "rar",
    "a",
    "-r",
    "-ol",
    f"-hp{password}",
    f"-mt{rar_threads}",
    archive_target,
    source_dir.name,
  ]

  entries, total_bytes = _collect_entries(source_dir)
  file_sizes = {}
  for path, arcname in entries:
    try:
      st = path.lstat()
    except OSError:
      continue
    if stat.S_ISREG(st.st_mode):
      file_sizes[arcname] = st.st_size

  reporter = ProgressReporter(logger, "Archiving", total_bytes)
  completed = set()
  completed_bytes = 0
  current_arcname = None
  current_pct = 0
  raw_output = []
  current_chars = []

  def handle_text(text: str) -> None:
    nonlocal completed_bytes, current_arcname, current_pct

    stripped = text.strip()
    if not stripped.startswith("Adding"):
      return

    name_match = re.match(r"Adding\s+(.*?)\s+(OK|(?:\d{1,3}%))\s*$", stripped)
    if not name_match:
      return

    raw_name = name_match.group(1).strip()
    suffix = name_match.group(2)
    clean_name = re.sub(r"\s+\d{1,3}%\s*$", "", raw_name).strip()
    clean_name = clean_name.replace("\\", "/").removeprefix("./")

    name = None
    if clean_name in file_sizes:
      name = clean_name
    elif f"{source_dir.name}/{clean_name}" in file_sizes:
      name = f"{source_dir.name}/{clean_name}"
    elif clean_name.removeprefix(f"{source_dir.name}/") in file_sizes:
      name = clean_name.removeprefix(f"{source_dir.name}/")

    if not name or name in completed:
      return

    size = file_sizes[name]
    done = suffix == "OK"

    if done:
      completed.add(name)
      completed_bytes += size
      if current_arcname == name:
        current_arcname = None
        current_pct = 0
      reporter.update(completed_bytes)
      return

    pct_match = re.match(r"(\d{1,3})%", suffix)
    pct = int(pct_match.group(1)) if pct_match else 0

    if name != current_arcname:
      current_arcname = name
      current_pct = pct
    else:
      current_pct = max(current_pct, pct)

    reporter.update(completed_bytes + size * current_pct // 100)

  master_fd = None
  slave_fd = None
  try:
    import pty
    master_fd, slave_fd = pty.openpty()
    stdout_target = slave_fd
  except (ImportError, OSError):
    stdout_target = subprocess.PIPE

  process = subprocess.Popen(
    command,
    stdout=stdout_target,
    stderr=stdout_target,
    stdin=subprocess.DEVNULL,
    cwd=source_dir.parent,
  )

  if slave_fd is not None:
    os.close(slave_fd)
    read_fd = master_fd
  else:
    read_fd = process.stdout.fileno() if process.stdout else None

  if read_fd is not None:
    while True:
      try:
        data = os.read(read_fd, 1024)
      except OSError:
        break
      if not data:
        break
      text = data.decode("utf-8", errors="replace")
      raw_output.append(text)
      for ch in text:
        if ch == "\b":
          if current_chars:
            current_chars.pop()
        elif ch in ("\r", "\n"):
          if current_chars:
            handle_text("".join(current_chars))
          current_chars = []
        else:
          current_chars.append(ch)
          if ch == "%":
            handle_text("".join(current_chars))
          elif len(current_chars) >= 2 and current_chars[-1] == "K" and current_chars[-2] == "O":
            handle_text("".join(current_chars))

    if current_chars:
      handle_text("".join(current_chars))

    if master_fd is not None:
      try:
        os.close(master_fd)
      except OSError:
        pass
    elif process.stdout:
      try:
        process.stdout.close()
      except OSError:
        pass

  returncode = process.wait()
  output_text = "".join(raw_output)

  if returncode not in (0, 1, 6):
    error_msg = output_text.strip() if output_text else f"exit code {returncode}"
    raise RuntimeError(f"RAR compression failed: {error_msg}")

  if returncode in (1, 6) and logger:
    logger.warning("RAR compression completed with non-fatal warnings (code %s)", returncode)

  if not archive_path.exists() or archive_path.stat().st_size == 0:
    error_msg = output_text.strip() if output_text else f"exit code {returncode}"
    raise RuntimeError(f"RAR compression failed to produce archive: {error_msg}")

  reporter.finish()

  return archive_path.stat().st_size if archive_path.exists() else 0


def extract_encrypted_zip(archive_path: Path, destination_dir: Path, password: str, logger) -> None:
  destination_dir.mkdir(parents=True, exist_ok=True)
  with pyzipper.AESZipFile(archive_path, "r") as zf:
    zf.setpassword(password.encode("utf-8"))
    zf.extractall(destination_dir)


def extract_encrypted_rar(archive_path: Path, destination_dir: Path, password: str, logger) -> None:
  destination_dir.mkdir(parents=True, exist_ok=True)
  command = [
    "rar",
    "x",
    "-y",
    "-ola",
    f"-hp{password}",
    str(archive_path.resolve()),
    f"{str(destination_dir.resolve())}/",
  ]

  result = subprocess.run(
    command,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    check=False,
  )

  if result.returncode not in (0, 1):
    error_msg = result.stdout.strip() if result.stdout else f"exit code {result.returncode}"
    raise RuntimeError(f"RAR extraction failed: {error_msg}")

  if result.returncode == 1 and logger:
    logger.warning("RAR extraction completed with non-fatal warnings (code 1)")
