#!/usr/bin/env bash
# Installs Zoo on a Linux host: Docker, Kata Containers (when the host has KVM), the pinned release's compose stack,
# and the `zoo` operator CLI.
#
#   curl -fsSL https://github.com/chann44/zoo/releases/latest/download/install.sh | sudo bash
#
# Options (or the matching environment variables):
#   --version X.Y.Z      release to install (ZOO_VERSION, default: the latest release)
#   --dir PATH           install directory (ZOO_HOME, default: /opt/zoo)
#   --admin-email EMAIL  account allowed to use the admin pages (ADMIN_EMAILS)
#   --domain HOST        serve the dashboard and API on https://HOST through Caddy (ZOO_DOMAIN)
#   --runc               skip Kata and run sandboxes as plain containers, without VM isolation
set -euo pipefail

REPO="chann44/zoo"
ZOO_HOME="${ZOO_HOME:-/opt/zoo}"
ZOO_VERSION="${ZOO_VERSION:-}"
ADMIN_EMAILS="${ADMIN_EMAILS:-}"
ZOO_DOMAIN="${ZOO_DOMAIN:-}"
KATA_VERSION="${KATA_VERSION:-latest}"
RUNTIME=kata

while [ $# -gt 0 ]; do
    case "$1" in
        --version) ZOO_VERSION="${2#v}"; shift 2 ;;
        --dir) ZOO_HOME="$2"; shift 2 ;;
        --admin-email) ADMIN_EMAILS="$2"; shift 2 ;;
        --domain) ZOO_DOMAIN="$2"; shift 2 ;;
        --runc) RUNTIME=runc; shift ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || die "Zoo installs on Linux. On a Mac or Windows machine, add it as a server from a Linux install."
[ "$(id -u)" -eq 0 ] || die "run as root: curl -fsSL .../install.sh | sudo bash"
case "$(uname -m)" in
    x86_64|amd64) ARCH=amd64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *) die "unsupported CPU architecture $(uname -m)" ;;
esac
# shellcheck source=/dev/null
. /etc/os-release 2>/dev/null || true
case "${ID:-}" in
    ubuntu|debian) ;;
    *) warn "tested on Ubuntu and Debian; continuing on ${PRETTY_NAME:-an unknown distribution}" ;;
esac
command -v curl >/dev/null || { apt-get update -qq && apt-get install -y -qq curl; }

# Docker

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    say "Installing Docker"
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true

# Kata, when the host can run VMs

kata_works() { docker run --rm --runtime kata alpine:3 true >/dev/null 2>&1; }

register_kata() {
    python3 - <<'PY'
import json, os
path = "/etc/docker/daemon.json"
config = json.load(open(path)) if os.path.exists(path) and os.path.getsize(path) else {}
config.setdefault("runtimes", {})["kata"] = {"runtimeType": "io.containerd.kata.v2"}
with open(path, "w") as f:
    json.dump(config, f, indent=2)
PY
    systemctl restart docker
}

install_kata() {
    local release asset url
    if [ "$KATA_VERSION" = latest ]; then
        release=https://api.github.com/repos/kata-containers/kata-containers/releases/latest
    else
        release="https://api.github.com/repos/kata-containers/kata-containers/releases/tags/$KATA_VERSION"
    fi
    url=$(curl -fsSL "$release" | grep -o "https://[^\"]*/kata-static-[^\"]*-${ARCH}\.tar\.\(xz\|zst\)" | head -n1)
    [ -n "$url" ] || return 1
    asset="/tmp/$(basename "$url")"
    say "Installing Kata Containers ($(basename "$url"))"
    curl -fsSL "$url" -o "$asset"
    case "$asset" in
        *.zst) command -v zstd >/dev/null || apt-get install -y -qq zstd; tar --zstd -xf "$asset" -C / ;;
        *) tar -xJf "$asset" -C / ;;
    esac
    rm -f "$asset"
    ln -sf /opt/kata/bin/containerd-shim-kata-v2 /usr/local/bin/containerd-shim-kata-v2
    ln -sf /opt/kata/bin/kata-runtime /usr/local/bin/kata-runtime
    register_kata
}

if [ "$RUNTIME" = kata ]; then
    if [ ! -e /dev/kvm ]; then
        warn "/dev/kvm is missing, so sandboxes can't run in their own VMs."
        warn "Falling back to runc: sandboxes share the host kernel. Use bare metal or a VM with nested virtualization for isolation."
        RUNTIME=runc
    elif kata_works; then
        say "Kata Containers already works"
    elif ! install_kata || ! kata_works; then
        warn "Kata Containers didn't start a test VM. Falling back to runc: sandboxes share the host kernel."
        warn "Fix Kata, set ZOO_RUNTIME=kata in $ZOO_HOME/.env and run: zoo upgrade"
        RUNTIME=runc
    else
        say "Kata Containers works"
    fi
fi

# Zoo

if [ -z "$ZOO_VERSION" ]; then
    ZOO_VERSION=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest" | sed 's#.*/tag/v##')
    [ -n "$ZOO_VERSION" ] || die "couldn't find the latest release of $REPO"
fi
ASSETS="https://github.com/$REPO/releases/download/v$ZOO_VERSION"
say "Installing Zoo $ZOO_VERSION into $ZOO_HOME"
mkdir -p "$ZOO_HOME/backups"
cd "$ZOO_HOME"
for file in compose.yml Caddyfile; do
    curl -fsSL "$ASSETS/$file" -o "$file"
done
curl -fsSL "$ASSETS/zoo" -o /usr/local/bin/zoo
chmod 755 /usr/local/bin/zoo

if [ -f .env ]; then
    say "Keeping the existing $ZOO_HOME/.env"
    sed -i "s/^ZOO_VERSION=.*/ZOO_VERSION=$ZOO_VERSION/" .env
else
    host=$(hostname -I 2>/dev/null | awk '{print $1}')
    host=${host:-localhost}
    if [ -n "$ZOO_DOMAIN" ]; then
        web="https://$ZOO_DOMAIN"
        api="https://$ZOO_DOMAIN/api"
    else
        web="http://$host:3000"
        api="http://$host:8000"
    fi
    umask 077
    cat > .env <<EOF
ZOO_VERSION=$ZOO_VERSION
ZOO_RUNTIME=$RUNTIME
JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')
# encrypts stored secrets; back it up, losing it makes them unreadable
ZOO_SECRETS_KEY=$(openssl rand -base64 48 | tr -d '\n')
ADMIN_EMAILS=$ADMIN_EMAILS
ZOO_API_URL=$api
CORS_ORIGINS=$web
ZOO_DOMAIN=$ZOO_DOMAIN
EOF
    if [ -n "$ZOO_DOMAIN" ]; then
        echo "COMPOSE_PROFILES=domain" >> .env
    fi
fi

say "Pulling images"
docker compose -p zoo pull --quiet
say "Starting Zoo"
docker compose -p zoo up -d
zoo wait

web=$(grep '^CORS_ORIGINS=' .env | cut -d= -f2-)
say "Zoo $ZOO_VERSION is running"
cat <<EOF

  Dashboard   $web
  Runtime     $RUNTIME
  Config      $ZOO_HOME/.env  (keep ZOO_SECRETS_KEY safe)

  Sign up in the dashboard${ADMIN_EMAILS:+ as $ADMIN_EMAILS for admin access}, then:
    zoo doctor     check KVM, runtime, disk, ports and DNS
    zoo upgrade    move to the latest release, with a backup and automatic rollback
    zoo backup     save the database to $ZOO_HOME/backups
EOF
