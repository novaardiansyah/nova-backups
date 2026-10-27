import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile

from .archive import (
  create_encrypted_rar,
  create_encrypted_zip,
  extract_encrypted_rar,
  extract_encrypted_zip,
)
from .logger import setup_logger
from .utils import format_size


def load_env_file(env_path: Path) -> None:
  if not env_path.exists():
    return
  with open(env_path, "r", encoding="utf-8") as f:
    for line in f:
      line = line.strip()
      if not line or line.startswith("#"):
        continue
      if "=" in line:
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'\"")
        if k and k not in os.environ:
          os.environ[k] = v


def calculate_sha256(file_path: Path) -> str:
  hasher = hashlib.sha256()
  with open(file_path, "rb") as f:
    while chunk := f.read(64 * 1024):
      hasher.update(chunk)
  return hasher.hexdigest()


def generate_test_dataset(source_dir: Path) -> tuple[dict[str, str], dict[str, int]]:
  subdirectories = [
    "configs",
    "docs/guides",
    "docs/specs/v1",
    "media/images",
    "media/raw",
    "scripts/utils",
    "logs/system/daily",
  ]
  for sub in subdirectories:
    (source_dir / sub).mkdir(parents=True, exist_ok=True)

  expected_hashes = {}
  expected_sizes = {}
  file_index = 0

  for folder in [""] + subdirectories:
    target_folder = source_dir / folder if folder else source_dir

    for i in range(1, 6):
      file_index += 1
      txt_path = target_folder / f"sample_{file_index}_{i}.txt"
      content = f"Test file content {file_index}-{i} in {folder}\n" * (i * 20)
      txt_path.write_text(content, encoding="utf-8")
      rel_posix = txt_path.relative_to(source_dir).as_posix()
      expected_hashes[rel_posix] = calculate_sha256(txt_path)
      expected_sizes[rel_posix] = txt_path.stat().st_size

    for j in range(1, 3):
      file_index += 1
      bin_path = target_folder / f"binary_{file_index}_{j}.dat"
      bin_size = (file_index % 7 + 1) * 8192
      bin_content = os.urandom(bin_size)
      bin_path.write_bytes(bin_content)
      rel_posix = bin_path.relative_to(source_dir).as_posix()
      expected_hashes[rel_posix] = calculate_sha256(bin_path)
      expected_sizes[rel_posix] = bin_path.stat().st_size

  return expected_hashes, expected_sizes


def run_test(logger=None) -> bool:
  if logger is None:
    logger = setup_logger()

  project_root = Path(__file__).resolve().parent.parent
  load_env_file(project_root / ".env")

  password = os.environ.get("ENCRYPT_PASSWORD")
  if not password:
    raise ValueError("ENCRYPT_PASSWORD is not set in environment or .env")

  encrypt_type = (os.environ.get("ENCRYPT_TYPE") or ".zip").strip().lower()
  if not encrypt_type.startswith("."):
    encrypt_type = f".{encrypt_type}"

  if encrypt_type not in (".zip", ".rar"):
    raise ValueError(f"Unsupported ENCRYPT_TYPE '{encrypt_type}'. Must be '.zip' or '.rar'")

  test_dir = Path(tempfile.mkdtemp(prefix="backup_test_"))
  source_dir = test_dir / "dataset"
  source_dir.mkdir(parents=True, exist_ok=True)
  extract_dir = test_dir / "extracted"
  archive_file = test_dir / f"test_backup{encrypt_type}"

  logger.info("========================================")
  logger.info("TEST: Starting compression and extraction test")
  logger.info("TEST: Archive type: %s", encrypt_type)

  try:
    expected_hashes, expected_sizes = generate_test_dataset(source_dir)
    total_files = len(expected_hashes)
    total_bytes = sum(expected_sizes.values())
    logger.info("TEST: Generated %d test files (%s)", total_files, format_size(total_bytes))

    logger.info("TEST: Compressing to %s...", archive_file.name)
    if encrypt_type == ".rar":
      create_encrypted_rar(source_dir, archive_file, password, logger)
    else:
      create_encrypted_zip(source_dir, archive_file, password, logger)

    if not archive_file.exists() or archive_file.stat().st_size == 0:
      raise RuntimeError(f"Archive file {archive_file} was not created or is empty")

    archive_size = archive_file.stat().st_size
    logger.info("TEST: Archive created successfully: %s (%s)", archive_file.name, format_size(archive_size))

    logger.info("TEST: Extracting archive to %s...", extract_dir)
    if encrypt_type == ".rar":
      extract_encrypted_rar(archive_file, extract_dir, password, logger)
    else:
      extract_encrypted_zip(archive_file, extract_dir, password, logger)

    extracted_root = extract_dir / source_dir.name if (extract_dir / source_dir.name).is_dir() else extract_dir
    extracted_files = {}

    for root, _, files in os.walk(extracted_root):
      for name in files:
        full_path = Path(root) / name
        rel_posix = full_path.relative_to(extracted_root).as_posix()
        extracted_files[rel_posix] = full_path

    logger.info("TEST: Extracted %d files. Verifying integrity...", len(extracted_files))

    if len(extracted_files) != total_files:
      missing = set(expected_hashes.keys()) - set(extracted_files.keys())
      extra = set(extracted_files.keys()) - set(expected_hashes.keys())
      raise RuntimeError(
        f"File count mismatch: expected {total_files}, got {len(extracted_files)}. "
        f"Missing: {missing}, Extra: {extra}"
      )

    for rel_posix, expected_hash in expected_hashes.items():
      extracted_path = extracted_files.get(rel_posix)
      if not extracted_path or not extracted_path.exists():
        raise RuntimeError(f"Extracted file missing: {rel_posix}")

      actual_size = extracted_path.stat().st_size
      expected_size = expected_sizes[rel_posix]
      if actual_size != expected_size:
        raise RuntimeError(
          f"File size mismatch for '{rel_posix}': expected {expected_size} bytes, got {actual_size} bytes"
        )

      actual_hash = calculate_sha256(extracted_path)
      if actual_hash != expected_hash:
        raise RuntimeError(
          f"Checksum mismatch for '{rel_posix}': data is corrupted!"
        )

    logger.info("TEST PASSED: All %d files successfully verified. Integrity 100%% intact.", total_files)
    logger.info("========================================")
    return True

  finally:
    shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
  try:
    ok = run_test()
    sys.exit(0 if ok else 1)
  except Exception as e:
    sys.stderr.write(f"TEST FAILED: {e}\n")
    sys.exit(1)
