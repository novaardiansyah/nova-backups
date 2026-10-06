ifeq ($(filter $(firstword $(MAKECMDGOALS)),docker-restore),$(firstword $(MAKECMDGOALS)))
  CMD_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(CMD_ARGS),)
    FILE ?= $(CMD_ARGS)
    $(eval $(CMD_ARGS):;@:)
  endif
endif

docker-build:
	clear
	
	@echo "[INFO] Docker Build is starting..."
	@echo "[INFO] Pulling latest changes from GitHub..."
	@git pull origin main

	@echo "[INFO] Killing docker compose..."
	docker compose kill || true

	@echo "[INFO] Removing docker compose..."
	docker compose down --remove-orphans

	@echo "[INFO] Building docker compose..."
	docker compose up -d --build

	@echo "[INFO] Applying permissions..."
	@make permissions

	@echo "[INFO] Docker Build is finished..."

docker-logs:
	clear
	docker compose logs -f

docker-backup:
	clear
	docker compose exec backup python -m app.main backup

docker-restore:
	clear
	docker compose exec backup python -m app.main restore $(FILE)

docker-schedules:
	clear
	docker compose exec backup python -m app.main schedules

permissions:
	@for f in .env .env.local .env.production .env.staging AGENTS.md Makefile; do \
		if [ -f "$$f" ]; then chmod 600 "$$f"; fi; \
	done
	@if [ -d .git ]; then \
		chmod 700 .git; \
		find .git -type f -exec chmod 600 {} +; \
		find .git -type d -exec chmod 700 {} +; \
	fi
