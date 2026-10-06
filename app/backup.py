from datetime import datetime
import os
from pathlib import Path
import pty
import re
import shutil
import subprocess
import sys
import time

from .gdrive import (
    is_gdrive_enabled,
    upload_file_to_gdrive,
)
from .logger import log_milestone
from .webhook import format_size, format_speed, send_webhook_notification


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


def run_backup(config, logger):
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

    backup_config = config["backup"]
    destination = Path(backup_config["destination"])
    sources = backup_config["sources"]
    excludes = config.get("exclude", [])

    timestamp = datetime.now().strftime("backup-%Y%m%d-%H%M%S")
    snapshot_dir = destination / timestamp
    rar_file = destination / f"{timestamp}.rar"

    destination.mkdir(parents=True, exist_ok=True)
    set_global_permissions(destination)
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    logger.info("========================================")
    logger.info("FULL BACKUP START")
    logger.info("Snapshot: %s", snapshot_dir)

    try:
        for item in sources:
            source_path = Path(item["source"])
            target_val = str(item.get("target", "")).strip()
            target_str = str(item["source"]) if target_val == "-" else str(item["target"])
            target_rel = target_str.lstrip("/")

            validate_source(source_path)

            target_path = snapshot_dir / target_rel

            if source_path.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                dest_path = target_path
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
                    f"{dest_path}/",
                ])
            else:
                if target_str.endswith("/") or target_path.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    dest_path = target_path / source_path.name
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    dest_path = target_path
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
                    str(dest_path),
                ])

            logger.info("Backing up: %s -> %s", source_path, dest_path)

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
                    f"rsync failed for '{source_path}' with exit code "
                    f"{result.returncode}"
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
            f"{timestamp}.rar",
            timestamp,
        ]

        returncode, rar_output = execute_rar(rar_command, destination, logger, snapshot_size)

        if returncode not in (0, 1):
            error_details = rar_output.strip()
            raise RuntimeError(
                f"rar compression failed with exit code {returncode}: {error_details}"
            )

        if not rar_file.exists() or rar_file.stat().st_size == 0:
            raise RuntimeError("rar archive was not created or is empty")

        set_global_permissions(rar_file)
        set_global_permissions(destination)

        shutil.rmtree(snapshot_dir, ignore_errors=True)

        logger.info("FULL BACKUP SUCCESS: %s", rar_file)

        if is_gdrive_enabled():
            try:
                upload_file_to_gdrive(rar_file, logger)
            except Exception:
                logger.exception("GOOGLE DRIVE UPLOAD FAILED")

        rar_size = rar_file.stat().st_size if rar_file.exists() else 0
        details = {
            "Snapshot": rar_file.name,
            "Size": format_size(rar_size),
            "Google Drive": "Uploaded" if is_gdrive_enabled() else "Disabled",
        }
        send_webhook_notification(
            title="Backup Finished",
            status="Success",
            details=details,
            duration_seconds=time.time() - start_time,
            logger=logger,
        )

    except Exception as err:
        logger.exception("FULL BACKUP FAILED")

        shutil.rmtree(snapshot_dir, ignore_errors=True)
        if rar_file.exists():
            rar_file.unlink(missing_ok=True)

        send_webhook_notification(
            title="Backup Failed",
            status="Failed",
            details={"Error": str(err)},
            duration_seconds=time.time() - start_time,
            logger=logger,
        )
        raise

    finally:
        logger.info("========================================")

