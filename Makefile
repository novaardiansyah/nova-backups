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
