from datetime import datetime, timezone
import json
from pathlib import Path


def get_pending_api_path() -> Path:
  app_dir = Path("/app")
  if app_dir.exists() and app_dir.is_dir():
    return app_dir / "pending_api.json"
  return Path("pending_api.json")


def load_pending_api_events() -> list[dict]:
  path = get_pending_api_path()
  if not path.is_file():
    return []
  try:
    with path.open("r", encoding="utf-8") as f:
      data = json.load(f)
  except Exception:
    return []
  if not isinstance(data, list):
    return []
  return [event for event in data if isinstance(event, dict)]


def save_pending_api_events(events: list[dict], logger=None) -> None:
  path = get_pending_api_path()
  try:
    if not events:
      path.unlink(missing_ok=True)
      return
    with path.open("w", encoding="utf-8") as f:
      json.dump(events, f, indent=2, ensure_ascii=False)
  except Exception as err:
    if logger:
      logger.warning(
        "Failed to write pending API events file '%s': %s", path, err
      )


def queue_pending_api_event(event_type: str, payload: dict, logger=None) -> None:
  events = load_pending_api_events()
  events.append(
    {
      "type": event_type,
      "payload": payload,
      "created_at": datetime.now(timezone.utc).isoformat(),
    }
  )
  save_pending_api_events(events, logger=logger)
  if logger:
    logger.warning(
      "Pending %s event saved to %s for later retry.",
      event_type,
      get_pending_api_path(),
    )


def retry_pending_api_events(logger=None) -> None:
  events = load_pending_api_events()
  if not events:
    return

  if logger:
    logger.info(
      "Retrying %d pending API event(s) from %s...",
      len(events),
      get_pending_api_path(),
    )

  from .api import mark_backup_schedule_started, send_backup_report

  remaining = []
  for event in events:
    event_type = event.get("type")
    payload = event.get("payload")
    success = False
    try:
      if event_type == "schedule_start" and isinstance(payload, dict):
        result = mark_backup_schedule_started(
          payload.get("schedule_id"), logger=logger
        )
        success = result is not None
      elif event_type == "backup_report" and isinstance(payload, dict):
        result = send_backup_report(payload, logger=logger)
        success = result is not None
      else:
        success = True
    except Exception as retry_err:
      if logger:
        logger.warning(
          "Failed to retry pending API event (%s): %s", event_type, retry_err
        )
    if not success:
      remaining.append(event)

  save_pending_api_events(remaining, logger=logger)

  if logger:
    succeeded = len(events) - len(remaining)
    if succeeded:
      logger.info(
        "Pending API events retried: %d succeeded, %d remaining.",
        succeeded,
        len(remaining),
      )