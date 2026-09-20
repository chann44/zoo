DB_FILE=./local.db
MIGRATION_DIR=./db/migrations

.PHONY: help create up down status reset generate run 

help:
	@echo "Available commands:        "
	@echo "make create name=<name>    --create a new migrations file"
	@echo "make up                    --Run pending migrations"
	@echo "make down                  --Rollback the last migrations"
	@echo "make status                --Check which migrations have been applied"
	@echo "make reset                 --rollback all the db (also wipes out the schema)"
	@echo "make generate              --run sqlc generate"

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
