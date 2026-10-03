import os
from pathlib import Path
import pty
import re
import subprocess
import sys

from .gdrive import (
    download_cloud_file,
    find_cloud_backup,
    get_cloud_backup_names,
    is_gdrive_enabled,
)
from .logger import log_milestone


def execute_rar_extract(rar_file: Path, recovery_dir: Path, rar_password: str, logger):
    command = [
        "rar",
        "x",
        "-y",
        "-ol",
        "-idc",
        "-idd",
        "-idn",
        f"-hp{rar_password}",
        str(rar_file),
        f"{str(recovery_dir)}/",
    ]

    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(recovery_dir),
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
    except Exception:
        os.close(slave_fd)
        os.close(master_fd)
        raise

    os.close(slave_fd)
    try:
        output_chunks = []
        last_percent = -1
        last_milestone = 0
        stream_buffer = ""
        is_tty = sys.stdout.isatty()

        while True:
            try:
                chunk = os.read(master_fd, 1024)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="ignore")
                output_chunks.append(text)
                stream_buffer += text

                matches = re.findall(r"(\d{1,3})%", stream_buffer)
                if matches:
                    val = int(matches[-1])
                    if 0 <= val <= 100 and val != last_percent:
                        last_percent = val
                        if is_tty:
                            sys.stdout.write(f"\rExtracting snapshot: {val}%")
                            sys.stdout.flush()

                        milestone = (val // 20) * 20
                        if milestone > last_milestone and milestone <= 100:
                            last_milestone = milestone
                            log_milestone(logger, f"Extracting snapshot: {milestone}%", is_tty)

                stream_buffer = stream_buffer[-32:]
            except OSError:
                break

        if is_tty and last_percent != -1:
            sys.stdout.write("\n")
            sys.stdout.flush()

        if last_milestone > 0 and last_milestone < 100:
            log_milestone(logger, "Extracting snapshot: 100%", is_tty)

        proc.wait()
        full_output = "".join(output_chunks)
        if proc.returncode not in (0, 1):
            error_details = full_output.strip()
            raise RuntimeError(
                f"rar extraction failed with exit code {proc.returncode}: {error_details}"
            )
        return proc.returncode, full_output
    finally:
        os.close(master_fd)


def get_recovery_destination(config: dict) -> Path:
    if Path("/recovery").exists():
        return Path("/recovery")

    env_dest = os.environ.get("RECOVERY_DESTINATION")
    if env_dest and Path(env_dest).exists():
        return Path(env_dest)

    backup_config = config.get("backup", {})
    destination = Path(backup_config.get("destination", "/backup"))
    return destination / "Recovery"


def set_global_permissions(target: Path):
    backup_path = Path("/backup")
    target_uid = backup_path.stat().st_uid if backup_path.exists() else 0
    target_gid = backup_path.stat().st_gid if backup_path.exists() else 0

    if target_uid != 0:
        subprocess.run(
            ["chown", "-R", f"{target_uid}:{target_gid}", str(target)],
            check=False,
        )

    subprocess.run(
        ["chmod", "-R", "777", str(target)],
        check=False,
    )

    try:
        os.chmod(target, 0o777)
        if target.is_dir():
            for root, dirs, files in os.walk(target):
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root, d), 0o777)
                    except OSError:
                        pass
                for f in files:
                    try:
                        os.chmod(os.path.join(root, f), 0o777)
                    except OSError:
                        pass
    except Exception:
        pass


def prompt_for_backup_file(destination: Path, logger) -> str:
    local_files = [
        item.name for item in destination.iterdir()
        if item.is_file() and item.name.endswith(".rar")
    ]
    local_files.sort(reverse=True)

    cloud_files = []
    if is_gdrive_enabled():
        try:
            cloud_files = get_cloud_backup_names()
            cloud_files.sort(reverse=True)
        except Exception:
            logger.warning("Could not list Google Drive files for selection")

    print("\n--- Available Backups ---")
    if local_files:
        print("Local backups:")
        for idx, name in enumerate(local_files, 1):
            print(f"  [{idx}] {name} (local)")
    else:
        print("Local backups: (none)")

    if cloud_files:
        print("Cloud backups (Google Drive):")
        for idx, name in enumerate(cloud_files, len(local_files) + 1):
            print(f"  [{idx}] {name} (cloud)")
    else:
        print("Cloud backups: (none)")

    all_files = local_files + cloud_files
    print("-------------------------\n")

    user_input = input("Enter backup filename (or number from list): ").strip()
    if not user_input:
        return ""

    if user_input.isdigit():
        choice = int(user_input)
        if 1 <= choice <= len(all_files):
            return all_files[choice - 1]

    return user_input


def run_restore(config: dict, logger, filename: str | None = None):
    rar_password = os.environ.get("RAR_PASSWORD") or os.environ.get("BACKUP_PASSWORD")
    if not rar_password:
        raise ValueError("RAR_PASSWORD is not set in environment")

    backup_config = config.get("backup", {})
    destination = Path(backup_config.get("destination", "/backup"))

    if not filename:
        filename = prompt_for_backup_file(destination, logger)

    if not filename:
        logger.error("No backup filename provided. Aborting restore.")
        raise ValueError("No backup filename provided")

    filename = filename.strip()
    if not filename.endswith(".rar"):
        filename += ".rar"

    logger.info("========================================")
    logger.info("RESTORE INITIATED: %s", filename)

    local_path = destination / filename

    if local_path.exists() and local_path.stat().st_size > 0:
        logger.info("Backup found locally: %s", local_path)
        target_file = local_path
    else:
        logger.info("Backup '%s' not found locally. Checking Google Drive...", filename)
        if not is_gdrive_enabled():
            raise FileNotFoundError(
                f"Backup file '{filename}' not found locally and Google Drive is not configured"
            )

        cloud_info = find_cloud_backup(filename)
        if not cloud_info:
            raise FileNotFoundError(
                f"Backup file '{filename}' was not found locally or in Google Drive"
            )

        logger.info("Found on Google Drive: %s. Downloading to %s...", filename, local_path)
        download_cloud_file(
            cloud_info["id"],
            local_path,
            int(cloud_info.get("size", 0)),
            logger,
        )
        set_global_permissions(local_path)
        target_file = local_path

    recovery_dir = get_recovery_destination(config)
    recovery_dir.mkdir(parents=True, exist_ok=True)
    set_global_permissions(recovery_dir)

    logger.info("Extracting %s to %s", target_file, recovery_dir)
    try:
        execute_rar_extract(target_file, recovery_dir, rar_password, logger)
        set_global_permissions(recovery_dir)
        logger.info("RESTORE SUCCESS: Extracted to %s", recovery_dir)
    except Exception:
        logger.exception("RESTORE FAILED")
        raise
    finally:
        logger.info("========================================")
