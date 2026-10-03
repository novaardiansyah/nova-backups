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
        for source in sources:
            name = source["name"]
            source_path = Path(source["path"])

            validate_source(source_path)

            target_path = snapshot_dir / name
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
                    f"rsync failed for '{name}' with exit code "
                    f"{result.returncode}"
                )

        logger.info("FULL BACKUP SUCCESS: %s", snapshot_dir)

    except Exception:
        logger.exception("FULL BACKUP FAILED")

        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise

    finally:
        logger.info("========================================")
