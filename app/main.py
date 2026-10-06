import sys

from .api import run_schedules
from .backup import run_backup
from .logger import setup_logger
from .restore import run_restore
from .scheduler import run_scheduler


def main():
    logger = setup_logger()
    mode = sys.argv[1] if len(sys.argv) > 1 else "scheduler"

    if mode in ("scheduler", "daemon", "start", "schedule"):
        try:
            run_scheduler(logger)
        except Exception:
            sys.exit(1)
        return

    if mode in ("schedules", "list", "fetch-schedules"):
        try:
            run_schedules(logger)
        except Exception:
            sys.exit(1)
        return

    if mode == "backup":
        try:
            run_backup({}, logger)
        except Exception:
            sys.exit(1)
        return

    if mode == "restore":
        filename = sys.argv[2] if len(sys.argv) > 2 else None
        try:
            run_restore({}, logger, filename)
        except Exception:
            sys.exit(1)
        return

    print("Usage:")
    print("  python -m app.main scheduler")
    print("  python -m app.main backup")
    print("  python -m app.main schedules")
    print("  python -m app.main restore [filename]")
    sys.exit(1)


if __name__ == "__main__":
    main()
