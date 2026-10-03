from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess


def validate_source(source_path: Path):
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if not source_path.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {source_path}")


def run_backup(config, logger):
    rar_password = os.environ.get("RAR_PASSWORD") or os.environ.get("BACKUP_PASSWORD")
    if not rar_password:
        raise ValueError("RAR_PASSWORD is not set in environment")

    backup_config = config["backup"]
    destination = Path(backup_config["destination"])
    sources = backup_config["sources"]
    excludes = config.get("exclude", [])

    timestamp = datetime.now().strftime("backup-%Y%m%d-%H%M%S")
    snapshot_dir = destination / timestamp
    rar_file = destination / f"{timestamp}.rar"

    destination.mkdir(parents=True, exist_ok=True)
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
            "-idq",
            "-y",
            f"-hp{rar_password}",
            f"{timestamp}.rar",
            timestamp,
        ]

        rar_result = subprocess.run(
            rar_command,
            cwd=str(destination),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

        if rar_result.stdout.strip():
            logger.info(rar_result.stdout.rstrip())

        if rar_result.returncode not in (0, 1):
            raise RuntimeError(
                f"rar compression failed with exit code {rar_result.returncode}"
            )

        if not rar_file.exists() or rar_file.stat().st_size == 0:
            raise RuntimeError("rar archive was not created or is empty")

        shutil.rmtree(snapshot_dir, ignore_errors=True)

        logger.info("FULL BACKUP SUCCESS: %s", rar_file)
        prune_backups(config, logger)

    except Exception:
        logger.exception("FULL BACKUP FAILED")

        shutil.rmtree(snapshot_dir, ignore_errors=True)
        if rar_file.exists():
            rar_file.unlink(missing_ok=True)
        raise

    finally:
        logger.info("========================================")


def get_snapshots(destination: Path):
    if not destination.exists() or not destination.is_dir():
        return []

    snapshots = [
        item for item in destination.iterdir()
        if item.is_dir() or (item.is_file() and item.name.endswith(".rar"))
    ]
    snapshots.sort(key=lambda p: p.name)
    return snapshots


def clean_backups(config, logger):
    backup_config = config["backup"]
    destination = Path(backup_config["destination"])
    snapshots = get_snapshots(destination)

    if not snapshots:
        logger.info("No backups found to delete.")
        return

    logger.info("========================================")
    logger.info("CLEAN ALL BACKUPS START")

    for snapshot in snapshots:
        if snapshot.is_dir():
            shutil.rmtree(snapshot, ignore_errors=True)
        else:
            snapshot.unlink(missing_ok=True)
        logger.info("Deleted snapshot: %s", snapshot)

    logger.info(
        "CLEAN ALL BACKUPS SUCCESS: Deleted %d snapshot(s).",
        len(snapshots),
    )
    logger.info("========================================")


def prune_backups(config, logger):
    backup_config = config["backup"]
    destination = Path(backup_config["destination"])
    snapshots = get_snapshots(destination)

    retention_val = backup_config.get("retention", config.get("retention", 0))
    try:
        retention = int(retention_val)
    except (ValueError, TypeError):
        retention = 0

    if retention <= 0:
        logger.info("Retention is set to %d. Skipping prune.", retention)
        return

    if len(snapshots) <= retention:
        logger.info(
            "Total snapshots (%d) within retention limit (%d). No pruning needed.",
            len(snapshots),
            retention,
        )
        return

    to_delete = snapshots[:-retention]

    logger.info("========================================")
    logger.info("PRUNE BACKUPS START (Retention: %d)", retention)

    for snapshot in to_delete:
        if snapshot.is_dir():
            shutil.rmtree(snapshot, ignore_errors=True)
        else:
            snapshot.unlink(missing_ok=True)
        logger.info("Pruned old snapshot: %s", snapshot)

    logger.info(
        "PRUNE BACKUPS SUCCESS: Deleted %d old snapshot(s), %d retained.",
        len(to_delete),
        retention,
    )
    logger.info("========================================")
