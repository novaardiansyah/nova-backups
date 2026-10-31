import sys

from .logger import setup_logger
from .scheduler import run_scheduler
from .utils import apply_resource_limits


def main():
  logger = setup_logger()
  apply_resource_limits(logger)
  action = sys.argv[1] if len(sys.argv) > 1 else "scheduler"
  if action == "test":
    from .test import run_test
    try:
      ok = run_test(logger)
      sys.exit(0 if ok else 1)
    except Exception as err:
      logger.error("Test failed: %s", err)
      sys.exit(1)

  try:
    run_scheduler(logger)
  except Exception:
    sys.exit(1)


if __name__ == "__main__":
    main()
