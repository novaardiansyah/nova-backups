import logging
from pathlib import Path


def setup_logger():
    Path("/app/logs").mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("nova-backup")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    file_handler = logging.FileHandler(
        "/app/logs/backup.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def log_milestone(logger, message: str, is_tty: bool):
    if is_tty:
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                record = logger.makeRecord(
                    logger.name,
                    logging.INFO,
                    "",
                    0,
                    message,
                    (),
                    None,
                )
                handler.handle(record)
    else:
        logger.info(message)

