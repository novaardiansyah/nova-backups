import sys

from .api import run_schedules
from .backup import clean_backups, prune_backups, run_backup
from .config import load_config
from .logger import setup_logger
from .restore import run_restore
from .scheduler import start_scheduler
from .sync import run_sync


def main():
    logger = setup_logger()
    mode = sys.argv[1] if len(sys.argv) > 1 else "schedule"

    if mode in ("schedules", "list", "fetch-schedules"):
        try:
            run_schedules(logger)
        except Exception:
            sys.exit(1)
        return

    try:
        config = load_config()
    except Exception:
        logger.exception("Failed to read config.yaml")
        sys.exit(1)

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

    if mode == "restore":
        filename = sys.argv[2] if len(sys.argv) > 2 else None
        try:
            run_restore(config, logger, filename)
        except Exception:
            sys.exit(1)
        return

    if mode == "sync":
        filename = sys.argv[2] if len(sys.argv) > 2 else None
        try:
            run_sync(config, logger, filename)
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
    print("  python -m app.main schedules")
    print("  python -m app.main backup")
    print("  python -m app.main clean")
    print("  python -m app.main prune")
    print("  python -m app.main restore [filename]")
    print("  python -m app.main sync [filename]")
    sys.exit(1)


if __name__ == "__main__":
    main()


