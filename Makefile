ifeq ($(filter $(firstword $(MAKECMDGOALS)),docker-sync docker-restore),$(firstword $(MAKECMDGOALS)))
  CMD_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(CMD_ARGS),)
    FILE ?= $(CMD_ARGS)
    $(eval $(CMD_ARGS):;@:)
  endif
endif

docker-build:
	clear
	docker compose down
	docker compose up -d --build

docker-logs:
	clear
	docker compose logs -f

docker-backup:
	clear
	docker compose exec backup python -m app.main backup

docker-restore:
	clear
	docker compose exec backup python -m app.main restore $(FILE)

docker-sync:
	clear
	docker compose exec backup python -m app.main sync $(FILE)

docker-schedules:
	clear
	docker compose exec backup python -m app.main schedules
	