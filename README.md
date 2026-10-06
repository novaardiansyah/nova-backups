# Nova Backups Manager

Hi Future Developer,

Welcome to **Nova Backups Manager**! This project is a containerized, automated backup and disaster-recovery solution designed to perform multi-source directory syncing, generate password-encrypted RAR snapshot archives, sync backups to Google Drive cloud storage, manage local/cloud retention lifecycles, and broadcast real-time HMAC-verified execution reports to Telegram webhooks.

> **Note:** This repository operates autonomously inside Docker, scheduling daily snapshots across multiple configured times, streaming compression and upload milestones, and providing an interactive restoration interface for rapid disaster recovery.

## Dazzling Tech Stack

- [Python 3.10+](https://www.python.org/) - Core backend application logic
- [Docker & Docker Compose](https://www.docker.com/) - Containerized deployment and isolated execution
- [RAR & UnRAR](https://www.rarlab.com/) - Password-protected encrypted snapshot compression (`-hp`)
- [rsync](https://rsync.samba.org/) - Fast, incremental multi-source directory synchronization
- [Google Drive API v3](https://developers.google.com/drive) - Resumable chunked cloud storage integration
- [APScheduler](https://apscheduler.readthedocs.io/) - Advanced cron-style multi-time background scheduler
- [PyYAML](https://pyyaml.org/) - Human-readable YAML configuration management
- [Requests](https://requests.readthedocs.io/) - HTTP library for Google Drive API and HMAC webhook delivery

## Telegram Webhook Notifications

Upon completing any backup, restore, clean, or pruning operation, the manager automatically constructs and dispatches an execution summary:

```text
Backup Finished

> Status: Success
> Device: Nova-Zorin
> Snapshot: backup-20261003-222538.rar
> Size: 0.13 MB
> Google Drive: Uploaded
> End Time: 2026-10-03 22:25:43 WIB
> Total Duration: 0m 5s
```

### Integration with personal-v4 & Direct Telegram Reporting

> [!NOTE]
> **Integration with personal-v4**
>
> This system is integrated with [personal-v4](https://github.com/novaardiansyah/personal-v4) for Telegram webhook notifications, database tracking, reporting, and management.
>
> However, you can also send webhook reports directly to Telegram without any intermediaries or third-party services.


## Core Features & Workflow

- **Multi-Source Aggregation**: Consolidate disparate project folders, host paths, or volumes into structured snapshot directories using `rsync`.
- **Encrypted Snapshot Archives**: Secure all backup archives with strong RAR header and content encryption (`-hp`), preventing unauthorized inspection.
- **Multiple Daily Schedules**: Run automated backups across multiple specific times per day (e.g., `10:00` and `15:00` WIB) with zero cron overhead.
- **Resumable Google Drive Sync**: Seamlessly upload snapshot archives to Google Drive folders with OAuth2 token auto-refresh and chunked uploading.
- **Dual Retention Management**: Independent retention thresholds for local disk and cloud storage to keep disk space lean while preserving archival history.
- **Interactive & Cloud-Aware Restore**: Easily restore any snapshot. If a backup is not present locally, it is automatically retrieved from Google Drive before extraction.
- **Bi-directional Snapshot Sync**: Synchronize snapshot archives between local disk and Google Drive by filename. Downloads the archive if missing locally, or uploads it if missing in the cloud.
- **HMAC-SHA256 Webhook Reporting**: Deliver verified execution reports, durations, and status updates directly to Telegram notification channels.
- **Resilient Error Handling**: Clean, user-friendly error diagnostics for password errors, archive corruption, and missing environments without noisy tracebacks.

## Quick Start & Setup

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/)
- Make (optional, for CLI shortcuts)

### Installation

```bash
# Clone repository
git clone https://github.com/novaardiansyah/nova-backups.git
cd nova-backups

# Setup configuration
cp .env-example .env
```

### Environment Configuration

Copy `.env-example` to `.env` and configure your credentials:

```env
# Google Drive Credentials (OAuth2)
OAUTH_CLIENT_ID="your_google_client_id"
OAUTH_CLIENT_SECRET="your_google_client_secret"
OAUTH_REFRESH_TOKEN="your_google_refresh_token"
GDRIVE_UPLOAD_PATH="/backups/nova-zorin"

# Docker & Backup Storage
BACKUP_DESTINATION="/home/user/Backups"
RECOVERY_DESTINATION="/home/user/Backups/Recovery"
RAR_PASSWORD="your_secure_encryption_password"

# Telegram Webhook Reporting
WEBHOOK_URL="https://your-webhook-domain.com/webhook/notifications/telegram"
WEBHOOK_SECRET="your_hmac_secret_key"
DEVICE_NAME="Nova-Zorin"

# API Service
API_URL="https://your-domain.com/api/system-backup"
API_EMAIL="system-backup@example.com"
API_PASSWORD="your_api_password"
SERVER_SLUG="your_server_slug"
```

### Running with Docker & Makefile

The project includes pre-configured `Makefile` commands for common operations:

```bash
# Build and start container in background
make docker-build

# Follow live container logs
make docker-logs

# Fetch backup schedules from API
make docker-schedules

# Trigger manual backup immediately
make docker-backup

# Restore backup interactively
make docker-restore

# Restore specific backup file
make docker-restore FILE=backup-20261003-222538.rar

# Sync specific backup file between local and Google Drive
make docker-sync FILE=backup-20261003-222538.rar

# Clean all local snapshots
make docker-clean-backup

# Prune snapshots based on retention limits
make docker-prune-backup
```

## Related Repositories

This project works in tandem with:

- **Personal Admin Panel (personal-v4)**: [https://github.com/novaardiansyah/personal-v4](https://github.com/novaardiansyah/personal-v4) - Central management dashboard built with [Laravel v12](https://laravel.com/docs/12.x) & [Filament v5](https://filamentphp.com/docs) for managing backup schedules, database tracking, reporting, and receiving webhook notifications.

## Credentials & Environment

While this repository is public, please note that all forms of credentials, API keys (including `.env`), and environment configurations are **not provided for the public**. Access to production systems and sensitive configurations remains restricted for security reasons.

## Let's Connect

Need to chat? Feel free to drop me a line via [Email](mailto:novaardiansyah78@gmail.com) or hit me up on [WhatsApp](https://wa.me/6289506668480?text=Hi%20Nova,%20I%20have%20a%20question%20about%20your%20project%20on%20GitHub:%20https://github.com/novaardiansyah/nova-backups). I'm just a message away, ready to groove with you!

## Project Status

![stages](https://img.shields.io/badge/stages-production-informational)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Google Drive](https://img.shields.io/badge/Google_Drive-Storage-yellow?logo=googledrive&logoColor=white)
![size](https://img.shields.io/github/repo-size/novaardiansyah/nova-backups?label=size&color=informational)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![last commit](https://img.shields.io/github/last-commit/novaardiansyah/nova-backups?label=last%20commit&color=informational)](commits/main)

## Code of Conduct

We believe in fostering a welcoming and inclusive environment for everyone. Please be respectful, considerate, and constructive in all interactions. Let's collaborate and make this community awesome together!

## Licensing Groove

Exciting news! This project is grooving to the rhythm of the [MIT License](LICENSE).

Feel free to use, modify, and share it with the world. Just remember to keep the original license intact. Let's spread the joy of coding together!

---

**Happy coding and collaborating!**  
— Nova Ardiansyah
