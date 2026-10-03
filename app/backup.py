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
    prune_cloud_backups,
    upload_file_to_gdrive,
)
from .logger import log_milestone
from .webhook import format_size, send_webhook_notification


def execute_rar(command: list[str], destination: Path, logger):
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
        last_milestone = 0
        stream_buffer = ""
        is_tty = sys.stdout.isatty()

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
                        if is_tty:
                            sys.stdout.write(f"\rCompressing snapshot: {val}%")
                            sys.stdout.flush()

                        milestone = (val // 20) * 20
                        if milestone > last_milestone and milestone <= 100:
                            last_milestone = milestone
                            log_milestone(logger, f"Compressing snapshot: {milestone}%", is_tty)

                stream_buffer = stream_buffer[-32:]
            except OSError:
                break

        if is_tty and last_percent != -1:
            sys.stdout.write("\n")
            sys.stdout.flush()

        if last_milestone > 0 and last_milestone < 100:
            log_milestone(logger, "Compressing snapshot: 100%", is_tty)

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

    if not source_path.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {source_path}")


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
            target_rel = str(item["target"]).lstrip("/")

            validate_source(source_path)

            target_path = snapshot_dir / target_rel
            target_path.parent.mkdir(parents=True, exist_ok=True)

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
                f"{target_path}/",
            ])

            logger.info("Backing up: %s -> %s", source_path, target_path)

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

        returncode, rar_output = execute_rar(rar_command, destination, logger)

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
                prune_cloud_backups(config, logger)
            except Exception:
                logger.exception("GOOGLE DRIVE UPLOAD/PRUNE FAILED")

        prune_local_backups(config, logger)

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


def get_snapshot_size(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        if path.is_file():
            return path.stat().st_size
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return 0


def get_snapshots(destination: Path):
    if not destination.exists() or not destination.is_dir():
        return []

    snapshots = [
        item for item in destination.iterdir()
        if item.name.startswith("backup-") and (
            item.is_dir() or item.name.endswith(".rar")
        )
    ]
    snapshots.sort(key=lambda p: p.name)
    return snapshots


def clean_backups(config, logger):
    start_time = time.time()
    backup_config = config["backup"]
    destination = Path(backup_config["destination"])
    snapshots = get_snapshots(destination)

    if not snapshots:
        logger.info("No local backups found to delete.")
        send_webhook_notification(
            title="Backup Clean Finished",
            status="Success",
            details={"Result": "No local backups found to delete"},
            duration_seconds=time.time() - start_time,
            logger=logger,
        )
        return

    logger.info("========================================")
    logger.info("CLEAN ALL LOCAL BACKUPS START")

    try:
        total_freed_bytes = sum(get_snapshot_size(s) for s in snapshots)
        for snapshot in snapshots:
            if snapshot.is_dir():
                shutil.rmtree(snapshot, ignore_errors=True)
            else:
                snapshot.unlink(missing_ok=True)
            logger.info("Deleted snapshot: %s", snapshot)

        logger.info(
            "CLEAN ALL LOCAL BACKUPS SUCCESS: Deleted %d snapshot(s).",
            len(snapshots),
        )
        send_webhook_notification(
            title="Backup Clean Finished",
            status="Success",
            details={
                "Deleted": f"{len(snapshots)} snapshot(s)",
                "Total Freed": format_size(total_freed_bytes),
            },
            duration_seconds=time.time() - start_time,
            logger=logger,
        )
    except Exception as err:
        logger.exception("CLEAN ALL LOCAL BACKUPS FAILED")
        send_webhook_notification(
            title="Backup Clean Failed",
            status="Failed",
            details={"Error": str(err)},
            duration_seconds=time.time() - start_time,
            logger=logger,
        )
        raise
    finally:
        logger.info("========================================")


def prune_local_backups(config, logger) -> tuple[int, int]:
    backup_config = config["backup"]
    destination = Path(backup_config["destination"])
    snapshots = get_snapshots(destination)

    retention_val = backup_config.get("retention", config.get("retention", 0))
    if isinstance(retention_val, dict):
        local_val = retention_val.get("local", 0)
    else:
        local_val = retention_val

    try:
        retention = int(local_val)
    except (ValueError, TypeError):
        retention = 0

    if retention <= 0:
        logger.info("Local retention is set to %d. Skipping local prune.", retention)
        return 0, 0

    if len(snapshots) <= retention:
        logger.info(
            "Total local snapshots (%d) within retention limit (%d). No pruning needed.",
            len(snapshots),
            retention,
        )
        return 0, 0

    to_delete = snapshots[:-retention]
    freed_bytes = sum(get_snapshot_size(s) for s in to_delete)

    logger.info("========================================")
    logger.info("PRUNE LOCAL BACKUPS START (Retention: %d)", retention)

    for snapshot in to_delete:
        if snapshot.is_dir():
            shutil.rmtree(snapshot, ignore_errors=True)
        else:
            snapshot.unlink(missing_ok=True)
        logger.info("Pruned old snapshot: %s", snapshot)

    logger.info(
        "PRUNE LOCAL BACKUPS SUCCESS: Deleted %d old snapshot(s), %d retained.",
        len(to_delete),
        retention,
    )
    logger.info("========================================")
    return len(to_delete), freed_bytes


def prune_backups(config, logger):
    start_time = time.time()
    try:
        local_count, local_freed = prune_local_backups(config, logger)
        cloud_count, cloud_freed = (0, 0)
        if is_gdrive_enabled():
            cloud_count, cloud_freed = prune_cloud_backups(config, logger)

        total_count = local_count + cloud_count
        total_freed = local_freed + cloud_freed

        if total_count == 0:
            details = {"Result": "All snapshots are within retention limits"}
        else:
            details = {
                "Total Pruned": f"{total_count} snapshot(s)",
                "Total Freed": format_size(total_freed),
            }
            if is_gdrive_enabled():
                details["Local Pruned"] = f"{local_count} snapshot(s) ({format_size(local_freed)})"
                details["Cloud Pruned"] = f"{cloud_count} snapshot(s) ({format_size(cloud_freed)})"

        send_webhook_notification(
            title="Backup Prune Finished",
            status="Success",
            details=details,
            duration_seconds=time.time() - start_time,
            logger=logger,
        )
    except Exception as err:
        send_webhook_notification(
            title="Backup Prune Failed",
            status="Failed",
            details={"Error": str(err)},
            duration_seconds=time.time() - start_time,
            logger=logger,
        )
        raise
