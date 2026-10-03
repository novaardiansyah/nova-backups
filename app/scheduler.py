from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler


def start_scheduler(config, backup_job, logger):
    schedule = config.get("schedule", {})
    backup_time = schedule.get("time", "02:00")

    try:
        hour, minute = map(int, backup_time.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        raise ValueError(
            "schedule.time must be in HH:MM format, e.g. 02:00"
        )

    timezone = ZoneInfo("Asia/Jakarta")

    scheduler = BlockingScheduler(timezone=timezone)

    scheduler.add_job(
        backup_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="daily-full-backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    logger.info(
        "Scheduler active. Daily full backup at %s WIB.",
        backup_time,
    )

    logger.info(
        "Current time: %s",
        datetime.now(timezone).strftime("%d/%m/%Y %H:%M:%S WIB"),
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
