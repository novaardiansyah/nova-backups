import os
from pathlib import Path

from .api import fetch_backup_schedules
from .archive import (
    ArchiveCorruptedError,
    ArchiveError,
    ArchivePasswordError,
    ArchiveWriteError,
    extract_encrypted_zip,
)
from .gdrive import (
    download_cloud_file,
    find_cloud_backup,
    get_cloud_backup_names,
    is_gdrive_enabled,
)


class RestoreError(Exception):
    pass


class IncorrectPasswordError(RestoreError):
    pass


def execute_zip_extract(zip_file: Path, recovery_dir: Path, zip_password: str, logger):
    try:
        extract_encrypted_zip(zip_file, recovery_dir, zip_password, logger)
    except ArchivePasswordError as err:
        raise IncorrectPasswordError(
            f"Incorrect password for '{zip_file.name}'. Please check ZIP_PASSWORD in your .env file."
        ) from err
    except ArchiveCorruptedError as err:
        raise RestoreError(
            f"Archive '{zip_file.name}' is damaged or corrupted: {err}"
        ) from err
    except ArchiveWriteError as err:
        raise RestoreError(
            f"Disk write error while extracting '{zip_file.name}'. Please check disk space and permissions. ({err})"
        ) from err
    except ArchiveError as err:
        raise RestoreError(f"zip extraction failed: {err}") from err


def get_recovery_destination(config: dict) -> Path:
    recovery_mount = Path("/recovery")
    if recovery_mount.exists():
        return recovery_mount

    backup_config = config.get("backup", {})
    destination = Path(backup_config.get("destination", "/backup"))
    return destination / "Recovery"


def prompt_for_backup_file(destination: Path, logger, gdrive_keys_list: list[dict] | None = None) -> str:
    local_files = [
        item.name for item in destination.iterdir()
        if item.is_file() and item.name.endswith(".zip")
    ]
    local_files.sort(reverse=True)

    cloud_files = []
    keys_to_check = gdrive_keys_list if gdrive_keys_list is not None else ([{}] if is_gdrive_enabled() else [])
    for k in keys_to_check:
        if is_gdrive_enabled(k):
            try:
                names = get_cloud_backup_names(keys=k)
                for name in names:
                    if name not in cloud_files:
                        cloud_files.append(name)
            except Exception:
                logger.warning("Could not list Google Drive files for selection")
    cloud_files.sort(reverse=True)

    print("\n--- Available Backups ---")
    if local_files:
        print("Local backups:")
        for idx, name in enumerate(local_files, 1):
            print(f"  [{idx}] {name} (local)")
    else:
        print("Local backups: (none)")

    if cloud_files:
        print("Cloud backups (Google Drive):")
        for idx, name in enumerate(cloud_files, len(local_files) + 1):
            print(f"  [{idx}] {name} (cloud)")
    else:
        print("Cloud backups: (none)")

    all_files = local_files + cloud_files
    print("-------------------------\n")

    user_input = input("Enter backup filename (or number from list): ").strip()
    if not user_input:
        return ""

    if user_input.isdigit():
        choice = int(user_input)
        if 1 <= choice <= len(all_files):
            return all_files[choice - 1]

    return user_input


def run_restore(config: dict, logger, filename: str | None = None):
    zip_password = os.environ.get("ZIP_PASSWORD") or os.environ.get("BACKUP_PASSWORD")
    if not zip_password:
        logger.error("RESTORE FAILED: ZIP_PASSWORD is not set in environment.")
        raise RestoreError("ZIP_PASSWORD is not set in environment")

    backup_config = config.get("backup", {})
    destination = Path(backup_config.get("destination", "/backup"))

    gdrive_keys_list = []
    try:
        schedules = fetch_backup_schedules(include_disabled=True, logger=logger)
        for s in schedules:
            provider_id = s.get("provider_id")
            if provider_id is not None and provider_id != 1:
                continue
            k = s.get("keys")
            if is_gdrive_enabled(k) and k not in gdrive_keys_list:
                gdrive_keys_list.append(k)
    except Exception as api_err:
        logger.warning("Could not retrieve backup schedules from API: %s", api_err)

    if not gdrive_keys_list and is_gdrive_enabled():
        gdrive_keys_list.append({})

    if not filename:
        filename = prompt_for_backup_file(destination, logger, gdrive_keys_list=gdrive_keys_list)

    if not filename:
        logger.error("RESTORE FAILED: No backup filename provided. Aborting restore.")
        raise RestoreError("No backup filename provided")

    filename = filename.strip()
    if not filename.endswith(".zip"):
        filename += ".zip"

    logger.info("========================================")
    logger.info("RESTORE INITIATED: %s", filename)

    try:
        local_path = destination / filename

        if local_path.exists() and local_path.stat().st_size > 0:
            logger.info("Backup found locally: %s", local_path)
            target_file = local_path
        else:
            logger.info("Backup '%s' not found locally. Checking Google Drive...", filename)
            if not gdrive_keys_list:
                raise RestoreError(
                    f"Backup file '{filename}' not found locally and Google Drive is not configured."
                )

            cloud_info = None
            matched_keys = None
            for k in gdrive_keys_list:
                try:
                    info = find_cloud_backup(filename, keys=k)
                    if info:
                        cloud_info = info
                        matched_keys = k
                        break
                except Exception:
                    continue

            if not cloud_info:
                raise RestoreError(
                    f"Backup file '{filename}' was not found locally or in Google Drive."
                )

            logger.info("Found on Google Drive: %s. Downloading to %s...", filename, local_path)
            download_cloud_file(
                cloud_info["id"],
                local_path,
                int(cloud_info.get("size", 0)),
                logger,
                keys=matched_keys,
            )
            target_file = local_path

        recovery_dir = get_recovery_destination(config)
        recovery_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Extracting %s to %s", target_file, recovery_dir)
        execute_zip_extract(target_file, recovery_dir, zip_password, logger)
        logger.info("RESTORE SUCCESS: Extracted to %s", recovery_dir)

    except RestoreError as err:
        logger.error("RESTORE FAILED: %s", err)
        raise
    except Exception as err:
        logger.exception("RESTORE FAILED")
        raise
    finally:
        logger.info("========================================")
