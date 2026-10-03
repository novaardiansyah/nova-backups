from pathlib import Path
import yaml


CONFIG_PATH = Path("/app/config.yaml")


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    if "backup" not in config:
        raise ValueError("'backup' section not found in config.yaml")

    backup = config["backup"]

    if not backup.get("destination"):
        raise ValueError("backup.destination is required")

    if not backup.get("sources"):
        raise ValueError("At least one backup.sources is required")

    for source in backup["sources"]:
        if not source.get("source") or not source.get("target"):
            raise ValueError("Each source must have 'source' and 'target'")

    return config
