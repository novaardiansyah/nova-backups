docker-build:
	docker compose down
	docker compose up -d --build

docker-logs:
	docker compose logs -f

docker-backup:
	docker compose exec backup python -m app.main backup
	