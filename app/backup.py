from datetime import datetime
import os
from pathlib import Path
import pty
import re
import shutil
import subprocess
import sys
import time

from .api import fetch_backup_schedules
from .gdrive import (
    is_gdrive_enabled,
    upload_file_to_gdrive,
)
from .logger import log_milestone, setup_logger
from .webhook import format_size, format_speed, send_webhook_notification


def get_snapshot_size(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        if path.is_file():
            return path.stat().st_size
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return 0


def execute_rar(command: list[str], destination: Path, logger, total_bytes: int = 0):
    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(destination),
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
        stream_buffer = ""
        is_tty = sys.stdout.isatty()
        start_time = time.time()
        last_sample_time = start_time
        last_sample_bytes = 0.0
        last_speed_str = "0 B/s"

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
                            sys.stdout.write(f"\rCompressing snapshot: {val}%{speed_display}\033[K")
                            sys.stdout.flush()

                        log_milestone(logger, f"Compressing snapshot: {val}%{speed_display}", is_tty)

                stream_buffer = stream_buffer[-32:]
            except OSError:
                break

        if is_tty and last_percent != -1:
            sys.stdout.write("\n")
            sys.stdout.flush()

        total_duration = time.time() - start_time
        avg_speed = total_bytes / total_duration if total_duration > 0 and total_bytes > 0 else 0
        final_speed_str = f" ({format_speed(avg_speed)})" if avg_speed > 0 else ""

        if last_percent != -1 and last_percent < 100:
            log_milestone(logger, f"Compressing snapshot: 100%{final_speed_str}", is_tty)

        proc.wait()
        full_output = "".join(output_chunks)
        return proc.returncode, full_output
    finally:
        os.close(master_fd)


def resolve_source_path(raw_path: str) -> Path:
    p = Path(raw_path)
    if p.exists():
        return p
    host_p = Path("/host") / raw_path.lstrip("/")
    if host_p.exists():
        return host_p
    return p


def resolve_destination_path(raw_path: str) -> Path:
    if not raw_path:
        return Path("/backup") if Path("/backup").exists() else Path("./backup")
    backup_env = os.environ.get("BACKUP_DESTINATION", "").strip().rstrip("/")
    if Path("/backup").exists():
        if backup_env and raw_path.startswith(backup_env):
            rel = raw_path[len(backup_env):].lstrip("/")
            return Path("/backup") / rel
        if raw_path.startswith("/backup"):
            return Path(raw_path)
        if "/Backups/" in raw_path:
            rel = raw_path.split("/Backups/", 1)[1]
            return Path("/backup") / rel
    return Path(raw_path)


def set_global_permissions(target: Path):
    backup_path = Path("/backup")
    target_uid = backup_path.stat().st_uid if backup_path.exists() else 0
    target_gid = backup_path.stat().st_gid if backup_path.exists() else 0

    if target_uid != 0:
        subprocess.run(
            ["chown", "-R", f"{target_uid}:{target_gid}", str(target)],
            check=False,
        )

    subprocess.run(
        ["chmod", "-R", "777", str(target)],
        check=False,
    )

    try:
        os.chmod(target, 0o777)
        if target.is_dir():
            for root, dirs, files in os.walk(target):
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root, d), 0o777)
                    except OSError:
                        pass
                for f in files:
                    try:
                        os.chmod(os.path.join(root, f), 0o777)
                    except OSError:
                        pass
    except Exception:
        pass


def validate_source(source_path: Path):
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if not (source_path.is_dir() or source_path.is_file()):
        raise ValueError(f"Source must be a file or directory: {source_path}")


def run_single_backup(schedule: dict, rar_password: str, logger) -> bool:
    start_time = time.time()
    schedule_id = schedule.get("id")
    name = schedule.get("name", "Unnamed")
    raw_source = schedule.get("source_path", "")
    raw_local_dest = schedule.get("local_destination_path", "")
    raw_cloud_dest = schedule.get("cloud_destination_path", "")
    filename_base = schedule.get("filename", "")
    is_sync_cloud = bool(schedule.get("is_sync_cloud", False))
    keep_local = bool(schedule.get("keep_local_backup", False))
    exclude_raw = schedule.get("exclude", "")

    if not filename_base:
        filename_base = datetime.now().strftime("backup-%Y%m%d-%H%M%S")

    if filename_base.endswith(".rar"):
        rar_filename = filename_base
        stem = filename_base[:-4]
    else:
        rar_filename = f"{filename_base}.rar"
        stem = filename_base

    destination_dir = resolve_destination_path(raw_local_dest)
    destination_dir.mkdir(parents=True, exist_ok=True)
    set_global_permissions(destination_dir)

    snapshot_dir = destination_dir / stem
    rar_file = destination_dir / rar_filename

    logger.info("========================================")
    logger.info("START BACKUP: %s (ID: %s)", name, schedule_id)
    logger.info("Local Destination: %s", destination_dir)
    logger.info("Archive Name: %s", rar_filename)

    excludes = []
    if isinstance(exclude_raw, str) and exclude_raw.strip():
        excludes = [x.strip() for x in exclude_raw.split(",") if x.strip()]
    elif isinstance(exclude_raw, list):
        excludes = [str(x).strip() for x in exclude_raw if str(x).strip()]

    try:
        source_path = resolve_source_path(raw_source)
        validate_source(source_path)

        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)
        snapshot_dir.mkdir(parents=True, exist_ok=False)

        logger.info("Backing up source: %s -> %s", source_path, snapshot_dir)

        if source_path.is_dir():
            command = [
                "rsync",
                "-a",
                "--human-readable",
                "--numeric-ids",
                "--delete",
            ]
            for pattern in excludes:
                command.append(f"--exclude={pattern}")
            command.extend([
                f"{source_path}/",
                f"{snapshot_dir}/",
            ])
        else:
            command = [
                "rsync",
                "-a",
                "--human-readable",
                "--numeric-ids",
            ]
            for pattern in excludes:
                command.append(f"--exclude={pattern}")
            command.extend([
                str(source_path),
                str(snapshot_dir / source_path.name),
            ])

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

        if result.stdout.strip():
            logger.info(result.stdout.rstrip())

        if result.returncode != 0:
            raise RuntimeError(
                f"rsync failed for '{source_path}' with exit code {result.returncode}"
            )

        logger.info("Compressing snapshot to encrypted RAR: %s", rar_file)
        snapshot_size = get_snapshot_size(snapshot_dir)

        rar_command = [
            "rar",
            "a",
            "-r",
            "-ol",
            "-idc",
            "-idd",
            "-idn",
            "-y",
            f"-hp{rar_password}",
            rar_filename,
            stem,
        ]

        returncode, rar_output = execute_rar(
            rar_command,
            destination_dir,
            logger,
            snapshot_size,
        )

        if returncode not in (0, 1):
            error_details = rar_output.strip()
            raise RuntimeError(
                f"rar compression failed with exit code {returncode}: {error_details}"
            )

        if not rar_file.exists() or rar_file.stat().st_size == 0:
            raise RuntimeError("rar archive was not created or is empty")

        set_global_permissions(rar_file)
        set_global_permissions(destination_dir)
        shutil.rmtree(snapshot_dir, ignore_errors=True)

        logger.info("BACKUP ARCHIVE CREATED: %s", rar_file)

        cloud_status = "Disabled"
        if is_sync_cloud and is_gdrive_enabled():
            try:
                cloud_folder = raw_cloud_dest or os.environ.get("GDRIVE_UPLOAD_PATH", "/backups/nova-zorin")
                upload_file_to_gdrive(rar_file, logger, folder_path=cloud_folder)
                cloud_status = "Uploaded"
                if not keep_local:
                    rar_file.unlink(missing_ok=True)
                    logger.info("Removed local archive per keep_local_backup=False")
            except Exception:
                cloud_status = "Upload Failed"
                logger.exception("GOOGLE DRIVE UPLOAD FAILED")

        rar_size = rar_file.stat().st_size if rar_file.exists() else 0
        details = {
            "Schedule": name,
            "Snapshot": rar_filename,
            "Size": format_size(rar_size) if rar_file.exists() else "Cleaned (Cloud Only)",
            "Google Drive": cloud_status,
            "Local Kept": "Yes" if keep_local else "No",
        }

        send_webhook_notification(
            title="Backup Finished",
            status="Success",
            details=details,
            duration_seconds=time.time() - start_time,
            logger=logger,
        )

        logger.info("BACKUP SUCCESS: %s", name)
        return True

    except Exception as err:
        logger.exception("BACKUP FAILED: %s", name)
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        if rar_file.exists():
            rar_file.unlink(missing_ok=True)

        send_webhook_notification(
            title="Backup Failed",
            status="Failed",
            details={
                "Schedule": name,
                "Error": str(err),
            },
            duration_seconds=time.time() - start_time,
            logger=logger,
        )
        return False

    finally:
        logger.info("========================================")


def run_backup(config=None, logger=None):
    if logger is None:
        if isinstance(config, type(setup_logger())):
            logger = config
        else:
            logger = setup_logger()

    start_time = time.time()
    rar_password = os.environ.get("RAR_PASSWORD") or os.environ.get("BACKUP_PASSWORD")
    if not rar_password:
        send_webhook_notification(
            title="Backup Failed",
            status="Failed",
            details={"Error": "RAR_PASSWORD is not set in environment"},
            duration_seconds=time.time() - start_time,
            logger=logger,
        )
        raise ValueError("RAR_PASSWORD is not set in environment")

    schedules = fetch_backup_schedules(logger=logger)
    if not schedules:
        logger.info("No backup schedules retrieved from API.")
        return

    enabled_schedules = [s for s in schedules if s.get("is_enabled", True)]
    if not enabled_schedules:
        logger.info("No enabled backup schedules to process.")
        return

    logger.info("Found %d enabled schedule(s) to backup.", len(enabled_schedules))

    success_count = 0
    fail_count = 0

    for schedule in enabled_schedules:
        success = run_single_backup(schedule, rar_password, logger)
        if success:
            success_count += 1
        else:
            fail_count += 1

    logger.info(
        "ALL BACKUP TASKS FINISHED: %d succeeded, %d failed.",
        success_count,
        fail_count,
    )

    if fail_count > 0 and success_count == 0:
        raise RuntimeError(f"All {fail_count} backup task(s) failed.")
