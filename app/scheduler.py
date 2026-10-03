from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler


def parse_schedule_times(schedule_config) -> list[tuple[int, int, str]]:
    raw = schedule_config.get("time") or schedule_config.get("times") or ["02:00"]
    if isinstance(raw, (str, int)):
        raw_items = [raw]
    elif isinstance(raw, list):
        raw_items = raw
    else:
        raise ValueError(
            "schedule.time must be in HH:MM format (e.g. '10:00' or ['10:00', '15:00'])"
        )

    parsed = []
    seen = set()

    for item in raw_items:
        try:
            if isinstance(item, int):
                hour, minute = divmod(item, 60)
            elif isinstance(item, str):
                hour_str, minute_str = item.strip().split(":")
                hour, minute = int(hour_str), int(minute_str)
            else:
                raise ValueError
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError(
                f"Invalid time format '{item}'. schedule.time must be in HH:MM format, e.g. 10:00"
            )

        formatted = f"{hour:02d}:{minute:02d}"
        if formatted not in seen:
            seen.add(formatted)
            parsed.append((hour, minute, formatted))

    if not parsed:
        raise ValueError("schedule.time must contain at least one valid time")

    parsed.sort(key=lambda x: (x[0], x[1]))
    return parsed


def start_scheduler(config, backup_job, logger):
    schedule = config.get("schedule", {})
    parsed_times = parse_schedule_times(schedule)

    timezone = ZoneInfo("Asia/Jakarta")
    scheduler = BlockingScheduler(timezone=timezone)

    for hour, minute, formatted in parsed_times:
        job_id = f"daily-full-backup-{formatted.replace(':', '')}"
        scheduler.add_job(
            backup_job,
            trigger="cron",
            hour=hour,
            minute=minute,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    time_str = ", ".join(item[2] for item in parsed_times)
    logger.info(
        "Scheduler active. Daily full backup at %s WIB.",
        time_str,
    )

    logger.info(
        "Current time: %s",
        datetime.now(timezone).strftime("%d/%m/%Y %H:%M:%S WIB"),
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
