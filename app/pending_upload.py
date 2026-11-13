from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from .gdrive import upload_file_to_gdrive
from .utils import cleanup_empty_directories


def get_pending_upload_path() -> Path:
  app_dir = Path("/app")
  if app_dir.exists() and app_dir.is_dir():
    return app_dir / "pending_uploads.json"
  return Path("pending_uploads.json")


def get_recovery_dir() -> Path:
  from .backup import resolve_destination_path
  return resolve_destination_path("") / "recovery"


def load_pending_uploads() -> list[dict]:
  path = get_pending_upload_path()
  if not path.is_file():
    return []
  try:
    with path.open("r", encoding="utf-8") as f:
      data = json.load(f)
  except Exception:
    return []
  if not isinstance(data, list):
    return []
  return [upload for upload in data if isinstance(upload, dict)]


def save_pending_uploads(uploads: list[dict], logger=None) -> None:
  path = get_pending_upload_path()
  try:
    if not uploads:
      path.unlink(missing_ok=True)
      return
    with path.open("w", encoding="utf-8") as f:
      json.dump(uploads, f, indent=2, ensure_ascii=False)
  except Exception as err:
    if logger:
      logger.warning("Failed to save pending uploads: %s", err)


def move_to_recovery(archive_file: Path, logger=None) -> Path:
  recovery_dir = get_recovery_dir()
  slot_name = f"{archive_file.stem}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
  slot_dir = recovery_dir / slot_name
  slot_dir.mkdir(parents=True, exist_ok=True)
  recovery_file = slot_dir / archive_file.name
  shutil.move(str(archive_file), str(recovery_file))
  if logger:
    logger.info("Failed upload moved to temporary storage: %s", recovery_file)
  return recovery_file


def queue_failed_upload(
  archive_file: Path,
  payload: dict,
  cloud_folder: str,
  keys: dict | None,
  error: str,
  report_id: int | str | None = None,
  keep_local: bool = False,
  logger=None,
) -> None:
  recovery_file = move_to_recovery(archive_file, logger)
  uploads = load_pending_uploads()
  uploads.append(
    {
      "payload": payload,
      "cloud_folder": cloud_folder,
      "keys": keys,
      "error": error,
      "report_id": report_id,
      "recovery_path": str(recovery_file),
      "original_path": str(archive_file),
      "keep_local": keep_local,
      "retry_count": 0,
      "failed_at": datetime.now(timezone.utc).isoformat(),
    }
  )
  save_pending_uploads(uploads, logger=logger)
  if logger:
    logger.warning("Saved pending upload for retry: %s", recovery_file.name)


def retry_pending_uploads(logger=None) -> None:
  uploads = load_pending_uploads()
  if not uploads:
    return

  from .api import delete_backup_report, send_backup_report

  if logger:
    logger.info("Retrying %d pending upload(s)...", len(uploads))

  remaining = []
  for upload in uploads:
    recovery_file = Path(upload["recovery_path"])
    if not recovery_file.is_file():
      if logger:
        logger.warning(
          "Pending upload file is missing, dropping retry record: %s", recovery_file
        )
      continue

    try:
      upload_file_to_gdrive(
        recovery_file,
        logger,
        folder_path=upload["cloud_folder"],
        keys=upload["keys"],
      )
    except Exception as err:
      upload["error"] = str(err)
      upload["retry_count"] = int(upload["retry_count"]) + 1
      upload["failed_at"] = datetime.now(timezone.utc).isoformat()
      if logger:
        logger.warning("Retry upload failed for '%s': %s", recovery_file.name, err)
      remaining.append(upload)
      continue

    payload = upload["payload"]
    payload["file_size"] = recovery_file.stat().st_size
    if payload["schedule_id"] is not None:
      send_backup_report(payload, logger=logger)

    if upload["keep_local"]:
      original_path = Path(upload["original_path"])
      try:
        original_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(recovery_file), str(original_path))
      except Exception as move_err:
        if logger:
          logger.warning(
            "Failed to restore local backup '%s': %s", original_path, move_err
          )
    else:
      recovery_file.unlink(missing_ok=True)
      cleanup_empty_directories(recovery_file.parent, stop_at=get_recovery_dir())

    if upload["report_id"] is not None:
      delete_backup_report(upload["report_id"], logger=logger)

    if logger:
      logger.info("Pending upload retried successfully: %s", recovery_file.name)

  save_pending_uploads(remaining, logger=logger)

  if logger and len(remaining) < len(uploads):
    logger.info(
      "Pending uploads retried: %d succeeded, %d remaining.",
      len(uploads) - len(remaining),
      len(remaining),
    )
