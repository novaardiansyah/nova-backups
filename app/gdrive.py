import os
from pathlib import Path
import sys
import time
import requests

from .logger import log_milestone
from .webhook import format_speed


def is_gdrive_enabled() -> bool:
    client_id = os.environ.get("OAUTH_CLIENT_ID")
    refresh_token = os.environ.get("OAUTH_REFRESH_TOKEN")
    return bool(client_id and refresh_token)


def get_access_token() -> str:
    client_id = os.environ.get("OAUTH_CLIENT_ID")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET")
    refresh_token = os.environ.get("OAUTH_REFRESH_TOKEN")
    token_uri = os.environ.get("OAUTH_TOKEN_URI", "https://oauth2.googleapis.com/token")

    if not client_id or not client_secret or not refresh_token:
        raise ValueError("Missing Google Drive OAuth credentials in environment")

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    resp = requests.post(token_uri, data=data, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to refresh Google Drive access token: {resp.status_code} {resp.text}"
        )

    token_json = resp.json()
    access_token = token_json.get("access_token")
    if not access_token:
        raise RuntimeError("No access_token returned by Google OAuth")

    return access_token


def parse_folder_path(path_str: str) -> list[str]:
    delimiter = ">" if ">" in path_str else "/"
    parts = [p.strip() for p in path_str.split(delimiter) if p.strip()]
    if parts and parts[0].lower() in ("drive saya", "my drive", "root"):
        parts = parts[1:]
    return parts


def get_or_create_folder(folder_path: str, access_token: str) -> str:
    parts = parse_folder_path(folder_path)
    if not parts:
        return "root"

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    current_parent_id = "root"

    for part in parts:
        safe_part = part.replace("'", r"\'")
        query = (
            f"name = '{safe_part}' and '{current_parent_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        params = {
            "q": query,
            "spaces": "drive",
            "fields": "files(id, name)",
        }

        resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params=params,
            timeout=30,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to query folder '{part}': {resp.status_code} {resp.text}"
            )

        files = resp.json().get("files", [])
        if files:
            current_parent_id = files[0]["id"]
        else:
            create_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            body = {
                "name": part,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [current_parent_id],
            }
            create_resp = requests.post(
                "https://www.googleapis.com/drive/v3/files",
                headers=create_headers,
                json=body,
                timeout=30,
            )
            if create_resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"Failed to create folder '{part}': {create_resp.status_code} {create_resp.text}"
                )
            current_parent_id = create_resp.json()["id"]

    return current_parent_id


def upload_file_to_gdrive(file_path: Path, logger, folder_path: str | None = None):
    access_token = get_access_token()
    target_folder = folder_path or os.environ.get("GDRIVE_UPLOAD_PATH", "/backups")
    folder_id = get_or_create_folder(target_folder, access_token)

    file_size = file_path.stat().st_size
    file_name = file_path.name

    logger.info("Uploading snapshot to Google Drive: %s -> %s", file_name, target_folder)

    init_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "application/x-rar-compressed",
        "X-Upload-Content-Length": str(file_size),
    }

    metadata = {
        "name": file_name,
        "parents": [folder_id],
    }

    init_resp = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
        headers=init_headers,
        json=metadata,
        timeout=30,
    )

    if init_resp.status_code != 200:
        raise RuntimeError(
            f"Failed to initiate resumable upload: {init_resp.status_code} {init_resp.text}"
        )

    upload_url = init_resp.headers.get("Location")
    if not upload_url:
        raise RuntimeError("Google Drive did not return a resumable upload Location header")

    chunk_size = 5 * 1024 * 1024
    uploaded = 0
    last_percent = -1
    is_tty = sys.stdout.isatty()
    start_time = time.time()
    last_speed_str = "0 B/s"

    with open(file_path, "rb") as f:
        while uploaded < file_size:
            chunk = f.read(chunk_size)
            chunk_len = len(chunk)
            if chunk_len == 0:
                break

            end = uploaded + chunk_len - 1
            chunk_headers = {
                "Content-Range": f"bytes {uploaded}-{end}/{file_size}",
                "Content-Length": str(chunk_len),
            }

            chunk_start = time.time()
            resp = requests.put(
                upload_url,
                data=chunk,
                headers=chunk_headers,
                timeout=60,
            )
            chunk_duration = time.time() - chunk_start
            if chunk_duration > 0:
                last_speed_str = format_speed(chunk_len / chunk_duration)

            if end < file_size - 1:
                if resp.status_code != 308:
                    raise RuntimeError(
                        f"Chunk upload error: expected 308, got {resp.status_code} {resp.text}"
                    )
            else:
                if resp.status_code not in (200, 201):
                    raise RuntimeError(
                        f"Final chunk upload error: {resp.status_code} {resp.text}"
                    )

            uploaded += chunk_len
            val = min(int(uploaded * 100 / file_size), 100)

            if is_tty:
                sys.stdout.write(f"\rUploading to Google Drive: {val}% ({last_speed_str})\033[K")
                sys.stdout.flush()

            if val != last_percent:
                last_percent = val
                log_milestone(logger, f"Uploading to Google Drive: {val}% ({last_speed_str})", is_tty)

    if is_tty and last_percent != -1:
        sys.stdout.write("\n")
        sys.stdout.flush()

    total_duration = time.time() - start_time
    avg_speed = file_size / total_duration if total_duration > 0 else 0
    final_speed_str = format_speed(avg_speed)

    if last_percent != -1 and last_percent < 100:
        log_milestone(logger, f"Uploading to Google Drive: 100% ({final_speed_str})", is_tty)

    logger.info("UPLOAD TO GOOGLE DRIVE SUCCESS: %s", file_name)


def list_cloud_backups(folder_id: str, access_token: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    query = (
        f"'{folder_id}' in parents and "
        f"mimeType != 'application/vnd.google-apps.folder' and trashed = false"
    )
    params = {
        "q": query,
        "spaces": "drive",
        "fields": "nextPageToken, files(id, name, createdTime, size)",
        "orderBy": "name",
        "pageSize": 100,
    }

    files = []
    page_token = None

    while True:
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params=params,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to list files in Google Drive: {resp.status_code} {resp.text}"
            )

        data = resp.json()
        files.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    files.sort(key=lambda x: x.get("name", ""))
    return files


def delete_cloud_file(file_id: str, access_token: str):
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    resp = requests.delete(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        headers=headers,
        timeout=30,
    )
    if resp.status_code not in (200, 204):
        raise RuntimeError(
            f"Failed to delete cloud file {file_id}: {resp.status_code} {resp.text}"
        )


def find_cloud_backup(filename: str) -> dict | None:
    if not is_gdrive_enabled():
        return None

    access_token = get_access_token()
    folder_path = os.environ.get("GDRIVE_UPLOAD_PATH", "/backups/nova-zorin")
    folder_id = get_or_create_folder(folder_path, access_token)

    safe_name = filename.replace("'", r"\'")
    query = (
        f"name = '{safe_name}' and '{folder_id}' in parents and "
        f"mimeType != 'application/vnd.google-apps.folder' and trashed = false"
    )
    params = {
        "q": query,
        "spaces": "drive",
        "fields": "files(id, name, size)",
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    resp = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers=headers,
        params=params,
        timeout=30,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to find cloud backup: {resp.status_code} {resp.text}"
        )

    files = resp.json().get("files", [])
    if files:
        return files[0]
    return None


def get_cloud_backup_names() -> list[str]:
    if not is_gdrive_enabled():
        return []

    access_token = get_access_token()
    folder_path = os.environ.get("GDRIVE_UPLOAD_PATH", "/backups/nova-zorin")
    folder_id = get_or_create_folder(folder_path, access_token)
    files = list_cloud_backups(folder_id, access_token)
    return [f.get("name", "") for f in files if f.get("name")]


def download_cloud_file(file_id: str, target_path: Path, expected_size: int, logger):
    access_token = get_access_token()
    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    resp = requests.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
        headers=headers,
        stream=True,
        timeout=60,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to download file from Google Drive: {resp.status_code} {resp.text}"
        )

    header_size = resp.headers.get("Content-Length")
    total_size = int(header_size) if header_size else expected_size

    downloaded = 0
    last_percent = -1
    is_tty = sys.stdout.isatty()
    start_time = time.time()
    last_sample_time = start_time
    last_sample_bytes = 0
    last_speed_str = "0 B/s"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target_path.with_suffix(".downloading")

    try:
        with open(temp_target, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    delta_time = now - last_sample_time
                    if delta_time >= 0.5:
                        speed = (downloaded - last_sample_bytes) / delta_time
                        last_speed_str = format_speed(speed)
                        last_sample_time = now
                        last_sample_bytes = downloaded

                    if total_size > 0:
                        val = min(int(downloaded * 100 / total_size), 100)
                        if is_tty:
                            sys.stdout.write(f"\rDownloading from Google Drive: {val}% ({last_speed_str})\033[K")
                            sys.stdout.flush()

                        if val != last_percent:
                            last_percent = val
                            log_milestone(logger, f"Downloading from Google Drive: {val}% ({last_speed_str})", is_tty)

        if is_tty and last_percent != -1:
            sys.stdout.write("\n")
            sys.stdout.flush()

        total_duration = time.time() - start_time
        avg_speed = total_size / total_duration if total_duration > 0 and total_size > 0 else 0
        final_speed_str = format_speed(avg_speed)

        if last_percent != -1 and last_percent < 100:
            log_milestone(logger, f"Downloading from Google Drive: 100% ({final_speed_str})", is_tty)

        temp_target.rename(target_path)
        logger.info("DOWNLOAD FROM GOOGLE DRIVE SUCCESS: %s", target_path.name)
    except Exception:
        temp_target.unlink(missing_ok=True)
        raise


