DB_FILE=./local.db
MIGRATION_DIR=./db/migrations

.PHONY: help create up down status reset generate run rotate-secrets guest-darwin guest-windows

help:
	@echo "Available commands:        "
	@echo "make create name=<name>    --create a new migrations file"
	@echo "make up                    --Run pending migrations"
	@echo "make down                  --Rollback the last migrations"
	@echo "make status                --Check which migrations have been applied"
	@echo "make reset                 --rollback all the db (also wipes out the schema)"
	@echo "make generate              --run sqlc generate"
	@echo "make rotate-secrets        --rewrap secret keys with ZOO_SECRETS_KEY or ZOO_KMS"
	@echo "make guest-darwin          --build zoo-guest for macOS VMs (guest/dist/)"
	@echo "make guest-windows         --build zoo-guest for Windows VMs (guest/dist/)"

create:
	@if [ -z "$(name)" ]; then echo "Error: 'name' variable is required. Example: make create name=add_users"; exit 1; fi
	goose -dir ${MIGRATION_DIR} create ${name} sql

up:
	goose -dir ${MIGRATION_DIR} sqlite3 ${DB_FILE} up
	sqlc generate

down:
	goose -dir ${MIGRATION_DIR} sqlite3 ${DB_FILE} down
	sqlc generate

status:
	goose -dir ${MIGRATION_DIR} sqlite3 ${DB_FILE} status

reset:
	goose -dir ${MIGRATION_DIR} sqlite3 ${DB_FILE} reset
	sqlc generate

generate:
	sqlc generate

rotate-secrets:
	uv run python -m server.rotate_secrets

guest-darwin:
	cd guest && CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags="-s -w" -o dist/zoo-guest-darwin-arm64 .

# windowsgui: the guest runs in the desktop session, where a console program would open a window
guest-windows:
	cd guest && CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags="-s -w -H windowsgui" -o dist/zoo-guest-windows-amd64.exe .
