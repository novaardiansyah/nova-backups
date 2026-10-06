import sys

from .api import run_schedules
from .backup import run_backup
from .logger import setup_logger
from .restore import run_restore
from .sync import run_sync


def main():
    logger = setup_logger()
    mode = sys.argv[1] if len(sys.argv) > 1 else "backup"

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

    if mode == "sync":
        filename = sys.argv[2] if len(sys.argv) > 2 else None
        try:
            run_sync({}, logger, filename)
        except Exception:
            sys.exit(1)
        return

    print("Usage:")
    print("  python -m app.main backup")
    print("  python -m app.main schedules")
    print("  python -m app.main restore [filename]")
    print("  python -m app.main sync [filename]")
    sys.exit(1)


if __name__ == "__main__":
    main()




