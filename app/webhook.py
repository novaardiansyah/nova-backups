from datetime import datetime
import hashlib
import hmac
import os
from zoneinfo import ZoneInfo

import requests


def is_webhook_enabled() -> bool:
    return bool(os.environ.get("WEBHOOK_URL") and os.environ.get("WEBHOOK_SECRET"))


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes = total_seconds // 60
    secs = total_seconds % 60
    return f"{minutes}m {secs}s"


def send_webhook_notification(
    title: str,
    status: str,
    details: dict[str, str] | None = None,
    duration_seconds: float | None = None,
    logger=None,
):
    if not is_webhook_enabled():
        return

    url = os.environ.get("WEBHOOK_URL", "").strip()
    secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    device = os.environ.get("DEVICE_NAME", "").strip()

    if not url or not secret:
        return

    tz = ZoneInfo("Asia/Jakarta")
    end_time_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    duration_str = (
        format_duration(duration_seconds)
        if duration_seconds is not None
        else "0m 0s"
    )

    lines = [
        f"*{title}*",
        "",
        f"> *Status*: {status}",
    ]

    if device:
        lines.append(f"> *Device*: {device}")

    if details:
        for key, value in details.items():
            lines.append(f"> *{key}*: {value}")

    lines.append(f"> *End Time*: {end_time_str} WIB")
    lines.append(f"> *Total Duration*: {duration_str}")

    message_text = "\n".join(lines)

    signature = hmac.new(
        secret.encode("utf-8"),
        end_time_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    payload = {
        "message": message_text,
        "timestamp": end_time_str,
    }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Signature": signature,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code >= 400 and logger:
            logger.warning(
                "Webhook notification failed with status %d: %s",
                resp.status_code,
                resp.text,
            )
        elif logger:
            logger.info("Webhook notification sent: %s (%s)", title, status)
    except Exception as err:
        if logger:
            logger.warning("Failed to send webhook notification: %s", err)
