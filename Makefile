# HTTP Delay Proxy - Development & Deployment Commands

.PHONY: install dev lint format typecheck check api worker rabbitmq build up down logs restart clean test

# Docker deployment
build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

pull:
	git pull

r: pull build down up

restart: build down up
	@echo "Services restarted successfully"

