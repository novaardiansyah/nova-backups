import os
from pathlib import Path
import sys
import time

from .backup import set_global_permissions
from .gdrive import (
    download_cloud_file,
    find_cloud_backup,
    get_cloud_backup_names,
    is_gdrive_enabled,
    upload_file_to_gdrive,
)
from .utils import format_size


class SyncError(Exception):
    pass


def prompt_for_sync_file(destination: Path, logger) -> str:
    destination.mkdir(parents=True, exist_ok=True)
    local_files = [
        item.name for item in destination.iterdir()
        if item.is_file() and item.name.endswith(".rar")
    ]
    local_files.sort(reverse=True)

    cloud_files = []
    if is_gdrive_enabled():
        try:
            cloud_files = get_cloud_backup_names()
            cloud_files.sort(reverse=True)
        except Exception:
            logger.warning("Could not list Google Drive files for selection")

    print("\n--- Available Files for Sync ---")
    if local_files:
        print("Local files:")
        for idx, name in enumerate(local_files, 1):
            status = "(local & cloud)" if name in cloud_files else "(local only)"
            print(f"  [{idx}] {name} {status}")
    else:
        print("Local files: (none)")

    cloud_only = [name for name in cloud_files if name not in local_files]
    if cloud_only:
        print("Cloud files (Google Drive):")
        for idx, name in enumerate(cloud_only, len(local_files) + 1):
            print(f"  [{idx}] {name} (cloud only)")
    elif not cloud_files:
        print("Cloud files: (none)")

    all_files = local_files + cloud_only
    print("--------------------------------\n")

    user_input = input("Enter filename to sync (or number from list): ").strip()
    if not user_input:
        return ""

    if user_input.isdigit():
        choice = int(user_input)
        if 1 <= choice <= len(all_files):
            return all_files[choice - 1]

    return user_input


def run_sync(config: dict, logger, filename: str | None = None):
    backup_config = config.get("backup", {})
    destination = Path(backup_config.get("destination", "/backup"))
    destination.mkdir(parents=True, exist_ok=True)

    if not filename:
        if sys.stdin.isatty():
            filename = prompt_for_sync_file(destination, logger)

    if not filename:
        logger.error("SYNC FAILED: No filename provided. Aborting sync.")
        raise SyncError("No filename provided")

    filename = Path(filename.strip()).name
    if not (destination / filename).exists() and not filename.endswith(".rar"):
        filename += ".rar"

    logger.info("========================================")
    logger.info("SYNC INITIATED: %s", filename)

    try:
        if not is_gdrive_enabled():
            raise SyncError("Google Drive is not configured in environment")

        local_path = destination / filename
        local_exists = local_path.exists() and local_path.is_file() and local_path.stat().st_size > 0

        cloud_info = find_cloud_backup(filename)
        cloud_exists = cloud_info is not None

        if not local_exists and not cloud_exists:
            raise SyncError(
                f"File '{filename}' was not found locally or in Google Drive."
            )

        if not local_exists and cloud_exists:
            cloud_size = int(cloud_info.get("size", 0))
            logger.info(
                "File '%s' not found locally but exists in Google Drive. Downloading (%s)...",
                filename,
                format_size(cloud_size),
            )
            download_cloud_file(
                cloud_info["id"],
                local_path,
                cloud_size,
                logger,
            )
            set_global_permissions(local_path)
            set_global_permissions(destination)
            logger.info("SYNC SUCCESS: Downloaded '%s' to %s", filename, local_path)
            return

        if local_exists and not cloud_exists:
            local_size = local_path.stat().st_size
            logger.info(
                "File '%s' exists locally (%s) but not in Google Drive. Uploading...",
                filename,
                format_size(local_size),
            )
            upload_file_to_gdrive(local_path, logger)
            logger.info("SYNC SUCCESS: Uploaded '%s' to Google Drive", filename)
            return

        local_size = local_path.stat().st_size
        logger.info(
            "File '%s' already exists both locally and in Google Drive. Already synchronized.",
            filename,
        )

    except SyncError as err:
        logger.error("SYNC FAILED: %s", err)
        raise
    except Exception as err:
        logger.exception("SYNC FAILED")
        raise
    finally:
        logger.info("========================================")
