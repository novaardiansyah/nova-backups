# Nova Backups Manager

Hi Future Developer,

Welcome to **Nova Backups Manager**! This project is a containerized, automated backup and disaster-recovery solution designed to perform multi-source directory syncing, generate password-encrypted ZIP snapshot archives, sync backups to Google Drive cloud storage, and manage local/cloud retention lifecycles.

> **Note:** This repository operates autonomously inside Docker, polling the central API at regular intervals (`BACKUP_INTERVAL`), streaming compression and cloud sync milestones directly to logs, and reporting execution status.

## Dazzling Tech Stack

- [Python 3.10+](https://www.python.org/) - Core backend application logic
- [Docker & Docker Compose](https://www.docker.com/) - Containerized deployment and isolated execution
- [pyzipper](https://github.com/danifus/pyzipper) - AES-256 password-encrypted ZIP snapshot compression
- [rsync](https://rsync.samba.org/) - Fast, incremental multi-source directory synchronization
- [Google Drive API v3](https://developers.google.com/drive) - Resumable chunked cloud storage integration
- [Requests](https://requests.readthedocs.io/) - HTTP library for API communication and Google Drive API

## Core Features & Workflow

- **Multi-Source Aggregation**: Consolidate disparate project folders, host paths, or volumes into structured snapshot directories using `rsync`.
- **Encrypted Snapshot Archives**: Secure all backup archives with AES-256 ZIP encryption, preventing unauthorized access to file contents.
- **Resumable Google Drive Sync**: Seamlessly upload snapshot archives to Google Drive folders with OAuth2 token auto-refresh and chunked uploading.
- **Autonomous Polling Scheduler**: Periodically queries the central management API for backup schedules and automatically executes tasks.
- **Resilient Error Handling**: Clean, user-friendly error diagnostics and automated execution reporting back to the API.

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
# APP
ENV="Local"
BACKUP_INTERVAL="5m"

# Docker & Backup Storage
BACKUP_DESTINATION="/home/user/Backups"
ZIP_PASSWORD="your_secure_encryption_password"

# API Service
API_URL="https://your-domain.com/api/system-backup"
API_EMAIL="system-backup@example.com"
API_PASSWORD="your_api_password"
SERVER_SLUG="your_server_slug"
```

### Running with Docker & Makefile

The project includes pre-configured `Makefile` commands for common operations:

```bash
# Build and start container with autonomous scheduler in background
make up

# Stop and remove container
make down

# Follow live container logs and scheduler execution
make docker-logs
```

## Related Repositories

This project works in tandem with:

- **Personal Admin Panel (personal-v4)**: [https://github.com/novaardiansyah/personal-v4](https://github.com/novaardiansyah/personal-v4) - Central management dashboard built with [Laravel v12](https://laravel.com/docs/12.x) & [Filament v5](https://filamentphp.com/docs) for managing backup schedules, database tracking, and reporting.

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
