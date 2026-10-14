import sys

from .logger import setup_logger
from .scheduler import run_scheduler


def main():
    logger = setup_logger()
    try:
        run_scheduler(logger)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
