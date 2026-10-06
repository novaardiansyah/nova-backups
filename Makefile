ifeq ($(filter $(firstword $(MAKECMDGOALS)),docker-sync docker-restore),$(firstword $(MAKECMDGOALS)))
  CMD_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(CMD_ARGS),)
    FILE ?= $(CMD_ARGS)
    $(eval $(CMD_ARGS):;@:)
  endif
endif

docker-build:
	docker compose down
	docker compose up -d --build

docker-logs:
	docker compose logs -f

docker-backup:
	docker compose exec backup python -m app.main backup

docker-clean-backup:
	docker compose exec backup python -m app.main clean

docker-backup-clean: docker-clean-backup

docker-prune-backup:
	docker compose exec backup python -m app.main prune

docker-restore:
	docker compose exec backup python -m app.main restore $(FILE)

docker-sync:
	docker compose exec backup python -m app.main sync $(FILE)

docker-schedules:
	docker compose exec backup python -m app.main schedules