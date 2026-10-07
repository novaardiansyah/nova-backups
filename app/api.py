from datetime import datetime, timezone
import os
from pathlib import Path
import requests

from .logger import setup_logger


def get_env_temp_path() -> Path:
    app_dir = Path("/app")
    if app_dir.exists() and app_dir.is_dir():
        return app_dir / ".env_temp"
    return Path(".env_temp")


def load_env_file(filepath: Path | None = None) -> dict[str, str]:
    if filepath is None:
        candidates = [
            Path("/app/.env"),
            Path(".env"),
            Path(__file__).resolve().parent.parent / ".env",
        ]
        for candidate in candidates:
            if candidate.is_file():
                filepath = candidate
                break
    if not filepath or not filepath.is_file():
        return {}

    loaded = {}
    try:
        with filepath.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    loaded[key] = val
    except Exception:
        return {}
    return loaded


def get_env_var(key: str) -> str | None:
    val = os.environ.get(key)
    if val is not None and val != "":
        return val
    env_vars = load_env_file()
    return env_vars.get(key) or None


def parse_iso_datetime(dt_str: str) -> datetime | None:
    if not dt_str:
        return None
    try:
        normalized = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def is_token_valid(token: str | None, expires_at_str: str | None) -> bool:
    if not token or not expires_at_str:
        return False
    expires_at = parse_iso_datetime(expires_at_str)
    if expires_at is None:
        return False
    now = datetime.now(timezone.utc)
    return (expires_at - now).total_seconds() > 60


def read_temp_env() -> dict[str, str]:
    path = get_env_temp_path()
    if not path.is_file():
        return {}
    data = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip().strip("'\"")
    except Exception:
        return {}
    return data


def write_temp_env(token: str, expires_at: str) -> None:
    path = get_env_temp_path()
    try:
        content = f'API_TOKEN="{token}"\nAPI_TOKEN_EXPIRES_AT="{expires_at}"\n'
        with path.open("w", encoding="utf-8") as f:
            f.write(content)
    except Exception as err:
        raise RuntimeError(f"Failed to write .env_temp: {err}") from err


def api_login(
    api_url: str | None = None,
    email: str | None = None,
    password: str | None = None,
    logger=None,
) -> tuple[str, str]:
    base_url = (api_url or get_env_var("API_URL") or "").rstrip("/")
    api_email = email or get_env_var("API_EMAIL")
    api_password = password or get_env_var("API_PASSWORD")

    if not base_url:
        raise ValueError("API_URL is required")
    if not api_email:
        raise ValueError("API_EMAIL is required")
    if not api_password:
        raise ValueError("API_PASSWORD is required")

    login_url = f"{base_url}/auth/login"
    payload = {
        "email": api_email,
        "password": api_password,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if logger:
        logger.info("Authenticating with API at %s...", login_url)

    resp = requests.post(login_url, json=payload, headers=headers, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"API login failed ({resp.status_code}): {resp.text}")

    resp_json = resp.json()
    if not resp_json.get("success"):
        msg = resp_json.get("message", "Unknown error")
        raise RuntimeError(f"API login unsuccessful: {msg}")

    data = resp_json.get("data")
    if not data or not isinstance(data, dict):
        raise RuntimeError("API login response missing data")

    token = data.get("token")
    expires_at = data.get("expires_at")

    if not token or not expires_at:
        raise RuntimeError("API login response missing token or expires_at")

    write_temp_env(token, expires_at)
    if logger:
        logger.info(
            "Authentication successful. Token saved to temporary storage (expires at: %s).",
            expires_at,
        )

    return token, expires_at


def get_valid_token(force_refresh: bool = False, logger=None) -> str:
    if not force_refresh:
        temp_data = read_temp_env()
        token = temp_data.get("API_TOKEN")
        expires_at = temp_data.get("API_TOKEN_EXPIRES_AT")

        if is_token_valid(token, expires_at):
            return str(token)

    token, _ = api_login(logger=logger)
    return token


def fetch_backup_schedules(
    server_slug: str | None = None,
    api_url: str | None = None,
    include_disabled: bool = False,
    logger=None,
) -> list[dict]:
    base_url = (api_url or get_env_var("API_URL") or "").rstrip("/")
    slug = server_slug or get_env_var("SERVER_SLUG")

    if not base_url:
        raise ValueError("API_URL is required")
    if not slug:
        raise ValueError("SERVER_SLUG is required")

    schedules_url = f"{base_url}/schedules"
    token = get_valid_token(logger=logger)

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    params = {
        "server_slug": slug,
    }
    if include_disabled:
        params["include_disabled"] = "1"

    if logger:
        logger.info("Requesting backup schedules from API for server '%s'...", slug)

    resp = requests.get(schedules_url, headers=headers, params=params, timeout=120)

    if resp.status_code == 401:
        if logger:
            logger.warning("Token expired or rejected. Refreshing token and retrying...")
        token = get_valid_token(force_refresh=True, logger=logger)
        headers["Authorization"] = f"Bearer {token}"
        resp = requests.get(schedules_url, headers=headers, params=params, timeout=120)

    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to retrieve schedules ({resp.status_code}): {resp.text}"
        )

    resp_json = resp.json()
    if not resp_json.get("success"):
        msg = resp_json.get("message", "Unknown error")
        raise RuntimeError(f"API returned error: {msg}")

    schedules = resp_json.get("data", [])
    if logger:
        logger.info("Successfully retrieved %d backup schedule(s) from API.", len(schedules))

    return schedules


def run_schedules(logger=None) -> list[dict]:
    if logger is None:
        logger = setup_logger()

    try:
        schedules = fetch_backup_schedules(logger=logger)
        if not schedules:
            logger.info("No backup schedules found for this server.")
            return []

        for idx, item in enumerate(schedules, 1):
            name = item.get("name", "Unnamed")
            backup_type = item.get("type", "files")
            source = item.get("source_path", "-")
            dest = item.get("local_destination_path", "-")
            cloud = item.get("cloud_destination_path", "-")
            enabled = item.get("is_enabled", False)
            exclude = item.get("exclude", "-")

            logger.info(
                "[%d] %s (Type: %s) | Enabled: %s | Source: %s | Local: %s | Cloud: %s | Exclude: %s",
                idx,
                name,
                backup_type,
                enabled,
                source,
                dest,
                cloud,
                exclude,
            )
        return schedules
    except Exception as err:
        logger.exception("Failed to fetch backup schedules: %s", err)
        raise


def send_backup_report(
    payload: dict,
    api_url: str | None = None,
    logger=None,
) -> dict | None:
    base_url = (api_url or get_env_var("API_URL") or "").rstrip("/")
    if not base_url:
        if logger:
            logger.warning("API_URL is not set. Skipping backup report.")
        return None

    backups_url = f"{base_url}/backups"
    token = get_valid_token(logger=logger)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    if logger:
        logger.info("Sending backup report to API (%s)...", payload.get("status"))

    resp = requests.post(backups_url, json=payload, headers=headers, timeout=120)

    if resp.status_code == 401:
        if logger:
            logger.warning("Token expired or rejected. Refreshing token and retrying...")
        token = get_valid_token(force_refresh=True, logger=logger)
        headers["Authorization"] = f"Bearer {token}"
        resp = requests.post(backups_url, json=payload, headers=headers, timeout=120)

    if resp.status_code not in (200, 201):
        if logger:
            logger.warning(
                "Failed to send backup report (%d): %s",
                resp.status_code,
                resp.text,
            )
        return None

    resp_json = resp.json()
    if logger:
        logger.info("Backup report successfully recorded by API.")
    return resp_json


def mark_backup_schedule_started(
    schedule_id: int | str,
    api_url: str | None = None,
    logger=None,
) -> dict | None:
    base_url = (api_url or get_env_var("API_URL") or "").rstrip("/")
    if not base_url:
        if logger:
            logger.warning("API_URL is not set. Skipping mark backup schedule started.")
        return None

    start_url = f"{base_url}/schedules/{schedule_id}/start"
    token = get_valid_token(logger=logger)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    if logger:
        logger.info("Notifying API that backup schedule ID %s has started...", schedule_id)

    resp = requests.post(start_url, headers=headers, timeout=120)

    if resp.status_code == 401:
        if logger:
            logger.warning("Token expired or rejected. Refreshing token and retrying...")
        token = get_valid_token(force_refresh=True, logger=logger)
        headers["Authorization"] = f"Bearer {token}"
        resp = requests.post(start_url, headers=headers, timeout=120)

    if resp.status_code not in (200, 201):
        if logger:
            logger.warning(
                "Failed to notify API of schedule start (%d): %s",
                resp.status_code,
                resp.text,
            )
        return None

    resp_json = resp.json()
    if logger:
        logger.info("Schedule ID %s start timestamp successfully recorded by API.", schedule_id)
    return resp_json



