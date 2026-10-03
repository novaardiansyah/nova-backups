from datetime import datetime
from pathlib import Path
import shutil
import subprocess


def validate_source(source_path: Path):
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    if not source_path.is_dir():
        raise NotADirectoryError(f"Source is not a directory: {source_path}")


def run_backup(config, logger):
    backup_config = config["backup"]
    destination = Path(backup_config["destination"])
    sources = backup_config["sources"]
    excludes = config.get("exclude", [])

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    snapshot_dir = destination / timestamp

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

        logger.info("FULL BACKUP SUCCESS: %s", snapshot_dir)
        prune_backups(config, logger)

    except Exception:
        logger.exception("FULL BACKUP FAILED")

        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise

    finally:
        logger.info("========================================")


def get_snapshots(destination: Path):
    if not destination.exists() or not destination.is_dir():
        return []

    snapshots = [
        item for item in destination.iterdir()
        if item.is_dir()
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
        shutil.rmtree(snapshot, ignore_errors=True)
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
        shutil.rmtree(snapshot, ignore_errors=True)
        logger.info("Pruned old snapshot: %s", snapshot)

    logger.info(
        "PRUNE BACKUPS SUCCESS: Deleted %d old snapshot(s), %d retained.",
        len(to_delete),
        retention,
    )
    logger.info("========================================")
