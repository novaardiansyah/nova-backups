ifeq ($(filter $(firstword $(MAKECMDGOALS)),docker-restore),$(firstword $(MAKECMDGOALS)))
  CMD_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(CMD_ARGS),)
    FILE ?= $(CMD_ARGS)
    $(eval $(CMD_ARGS):;@:)
  endif
endif

docker-build:
	clear
	docker compose kill || true
	docker compose down --remove-orphans
	docker compose up -d --build
	@make permissions

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
