ifeq ($(filter $(firstword $(MAKECMDGOALS)),docker-restore),$(firstword $(MAKECMDGOALS)))
  CMD_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(CMD_ARGS),)
    FILE ?= $(CMD_ARGS)
    $(eval $(CMD_ARGS):;@:)
  endif
endif

up:
	clear
	
	@echo "[INFO] Docker Build is starting..."
	@echo "[INFO] Pulling latest changes from GitHub..."
	@git restore .
	@git pull origin main

	@make down

	@echo "[INFO] Building docker compose..."
	docker compose up -d --build

	@echo "[INFO] Applying permissions..."
	@make permissions

	@echo "[INFO] Docker Build is finished..."

down:
	@echo "[INFO] Killing docker compose..."
	docker compose kill || true

	@echo "[INFO] Removing docker compose..."
	docker compose down --remove-orphans

docker-logs:
	clear
	docker compose logs -f

backup:
	clear
	docker compose exec backup python -m app.main backup

restore:
	clear
	docker compose exec backup python -m app.main restore $(FILE)

schedules:
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
