import sys

from .backup import clean_backups, prune_backups, run_backup
from .config import load_config
from .logger import setup_logger
from .scheduler import start_scheduler


def main():
    logger = setup_logger()

    try:
        config = load_config()
    except Exception:
        logger.exception("Failed to read config.yaml")
        sys.exit(1)

    mode = sys.argv[1] if len(sys.argv) > 1 else "schedule"

    if mode == "backup":
        try:
            run_backup(config, logger)
        except Exception:
            sys.exit(1)
        return

    if mode == "clean":
        try:
            clean_backups(config, logger)
        except Exception:
            sys.exit(1)
        return

    if mode == "prune":
        try:
            prune_backups(config, logger)
        except Exception:
            sys.exit(1)
        return

    if mode == "schedule":
        try:
            start_scheduler(
                config,
                lambda: run_backup(config, logger),
                logger,
            )
        except Exception:
            logger.exception("Scheduler stopped due to an error")
            sys.exit(1)
        return

    print("Usage:")
    print("  python -m app.main schedule")
    print("  python -m app.main backup")
    print("  python -m app.main clean")
    print("  python -m app.main prune")
    sys.exit(1)


if __name__ == "__main__":
    main()
