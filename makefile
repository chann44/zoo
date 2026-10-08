DB_FILE=./local.db
MIGRATION_DIR=./db/migrations

VERSION ?= $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)

.PHONY: help create up down status reset generate run rotate-secrets guest-darwin guest-windows proto node-dist

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

# after changing node/proto/node.proto (needs protoc, protoc-gen-go and protoc-gen-go-grpc)
proto:
	cd node && protoc -I proto --go_out=nodepb --go_opt=paths=source_relative --go-grpc_out=nodepb --go-grpc_opt=paths=source_relative proto/node.proto
	uv run python -m grpc_tools.protoc -Iserver/nodepb=node/proto --python_out=. --pyi_out=. --grpc_python_out=. server/nodepb/node.proto

# zoo-node for every host platform, with the API's version, for installers and auto-update (node/dist/)
node-dist:
	cd node && for t in linux/amd64 linux/arm64 darwin/arm64 windows/amd64; do \
		os=$${t%/*}; arch=$${t#*/}; ext=$$( [ $$os = windows ] && echo .exe ); \
		CGO_ENABLED=0 GOOS=$$os GOARCH=$$arch go build -trimpath -ldflags="-s -w -X main.version=$(VERSION)" -o dist/zoo-node-$$os-$$arch$$ext . || exit 1; \
	done && echo $(VERSION) > dist/VERSION
