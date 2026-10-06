import os
from pathlib import Path
import pty
import re
import subprocess
import sys
import time

from .backup import set_global_permissions
from .gdrive import (
    download_cloud_file,
    find_cloud_backup,
    get_cloud_backup_names,
    is_gdrive_enabled,
)
from .logger import log_milestone
from .utils import format_speed


class RestoreError(Exception):
    pass


class IncorrectPasswordError(RestoreError):
    pass


def execute_rar_extract(rar_file: Path, recovery_dir: Path, rar_password: str, logger):
    recovery_dir.mkdir(parents=True, exist_ok=True)
    target_path = str(recovery_dir).rstrip("/") + "/"
    command = [
        "rar",
        "x",
        "-y",
        "-ol",
        "-idc",
        "-idd",
        "-idn",
        f"-hp{rar_password}",
        str(rar_file),
        target_path,
    ]

    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(recovery_dir),
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
    except Exception:
        os.close(slave_fd)
        os.close(master_fd)
        raise

    os.close(slave_fd)
    try:
        output_chunks = []
        last_percent = -1
        last_milestone = 0
        stream_buffer = ""
        is_tty = sys.stdout.isatty()
        start_time = time.time()
        last_sample_time = start_time
        last_sample_bytes = 0.0
        last_speed_str = "0 B/s"
        total_bytes = rar_file.stat().st_size if rar_file.exists() else 0

        while True:
            try:
                chunk = os.read(master_fd, 1024)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="ignore")
                output_chunks.append(text)
                stream_buffer += text

                matches = re.findall(r"(\d{1,3})%", stream_buffer)
                if matches:
                    val = int(matches[-1])
                    if 0 <= val <= 100 and val != last_percent:
                        last_percent = val

                        if total_bytes > 0:
                            current_processed = total_bytes * (val / 100.0)
                            now = time.time()
                            delta_time = now - last_sample_time
                            if delta_time >= 0.5:
                                speed = (current_processed - last_sample_bytes) / delta_time
                                last_speed_str = format_speed(speed)
                                last_sample_time = now
                                last_sample_bytes = current_processed
                            elif last_speed_str == "0 B/s":
                                elapsed = now - start_time
                                if elapsed > 0:
                                    last_speed_str = format_speed(current_processed / elapsed)
                            speed_display = f" ({last_speed_str})"
                        else:
                            speed_display = ""

                        if is_tty:
                            sys.stdout.write(f"\rExtracting snapshot: {val}%{speed_display}\033[K")
                            sys.stdout.flush()

                        milestone = (val // 25) * 25
                        if milestone > 0 and milestone > last_milestone:
                            last_milestone = milestone
                            log_milestone(logger, f"Extracting snapshot: {milestone}%{speed_display}", is_tty)

                stream_buffer = stream_buffer[-32:]
            except OSError:
                break

        if is_tty and last_percent != -1:
            sys.stdout.write("\n")
            sys.stdout.flush()

        total_duration = time.time() - start_time
        avg_speed = total_bytes / total_duration if total_duration > 0 and total_bytes > 0 else 0
        final_speed_str = f" ({format_speed(avg_speed)})" if avg_speed > 0 else ""

        if last_percent != -1 and last_milestone < 100:
            log_milestone(logger, f"Extracting snapshot: 100%{final_speed_str}", is_tty)
            last_milestone = 100

        proc.wait()
        full_output = "".join(output_chunks)
        if proc.returncode not in (0, 1):
            error_details = full_output.strip()
            lower_err = error_details.lower()
            if proc.returncode == 11 or "incorrect password" in lower_err or "wrong password" in lower_err:
                raise IncorrectPasswordError(
                    f"Incorrect password for '{rar_file.name}'. Please check RAR_PASSWORD in your .env file."
                )
            if proc.returncode == 3 or "crc error" in lower_err or "checksum error" in lower_err:
                raise RestoreError(
                    f"Archive '{rar_file.name}' is damaged or corrupted (CRC error)."
                )
            if proc.returncode == 5 or "write error" in lower_err:
                raise RestoreError(
                    f"Disk write error while extracting '{rar_file.name}'. Please check disk space and permissions."
                )
            raise RestoreError(
                f"rar extraction failed with exit code {proc.returncode}: {error_details}"
            )
        return proc.returncode, full_output
    finally:
        os.close(master_fd)


def get_recovery_destination(config: dict) -> Path:
    backup_config = config.get("backup", {})
    destination = Path(backup_config.get("destination", "/backup"))

    recovery_mount = Path("/recovery")
    try:
        recovery_mount.mkdir(parents=True, exist_ok=True)
        probe_file = recovery_mount / ".probe"
        probe_file.touch()
        probe_file.unlink()
        return recovery_mount
    except OSError:
        pass

    recovery_local = destination / "Recovery"
    recovery_local.mkdir(parents=True, exist_ok=True)
    return recovery_local


def prompt_for_backup_file(destination: Path, logger) -> str:
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
    rar_password = os.environ.get("RAR_PASSWORD") or os.environ.get("BACKUP_PASSWORD")
    if not rar_password:
        logger.error("RESTORE FAILED: RAR_PASSWORD is not set in environment.")
        raise RestoreError("RAR_PASSWORD is not set in environment")

    backup_config = config.get("backup", {})
    destination = Path(backup_config.get("destination", "/backup"))

    if not filename:
        filename = prompt_for_backup_file(destination, logger)

    if not filename:
        logger.error("RESTORE FAILED: No backup filename provided. Aborting restore.")
        raise RestoreError("No backup filename provided")

    filename = filename.strip()
    if not filename.endswith(".rar"):
        filename += ".rar"

    logger.info("========================================")
    logger.info("RESTORE INITIATED: %s", filename)

    try:
        local_path = destination / filename

        if local_path.exists() and local_path.stat().st_size > 0:
            logger.info("Backup found locally: %s", local_path)
            target_file = local_path
        else:
            logger.info("Backup '%s' not found locally. Checking Google Drive...", filename)
            if not is_gdrive_enabled():
                raise RestoreError(
                    f"Backup file '{filename}' not found locally and Google Drive is not configured."
                )

            cloud_info = find_cloud_backup(filename)
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
            )
            set_global_permissions(local_path)
            set_global_permissions(destination)
            target_file = local_path

        recovery_dir = get_recovery_destination(config)
        recovery_dir.mkdir(parents=True, exist_ok=True)
        set_global_permissions(recovery_dir)

        logger.info("Extracting %s to %s", target_file, recovery_dir)
        execute_rar_extract(target_file, recovery_dir, rar_password, logger)
        set_global_permissions(recovery_dir)
        logger.info("RESTORE SUCCESS: Extracted to %s", recovery_dir)

    except RestoreError as err:
        logger.error("RESTORE FAILED: %s", err)
        raise
    except Exception as err:
        logger.exception("RESTORE FAILED")
        raise
    finally:
        logger.info("========================================")
