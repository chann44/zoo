#!/usr/bin/env bash
# Installs Zoo. Without --node, on Linux: the control plane, with Docker, Kata Containers (when the host has KVM),
# the pinned release's compose stack and the `zoo` operator CLI.
#
#   curl -fsSL https://github.com/chann44/zoo/releases/latest/download/install.sh | sudo bash
#
# With --node, on a Linux server or an Apple Silicon Mac: prepares the machine to run sandboxes for an existing
# control plane, and prints a join line to paste into the dashboard (Servers > Add server, which shows this command
# with --key and --control-plane filled in). Windows machines use install-node.ps1.
#
# Options (or the matching environment variables):
#   --version X.Y.Z      release to install (ZOO_VERSION, default: the latest release)
#   --dir PATH           install directory (ZOO_HOME, default: /opt/zoo)
#   --admin-email EMAIL  account allowed to use the admin pages (ADMIN_EMAILS)
#   --domain HOST        serve the dashboard and API on https://HOST through Caddy (ZOO_DOMAIN)
#   --runc               skip Kata and run sandboxes as plain containers, without VM isolation
#   --node               set up a server for an existing control plane instead
#   --key KEY            the control plane's SSH public key, authorized on the server (--node)
#   --control-plane URL  the control plane's API URL, checked for reachability (--node)
#   --user USER          the account the control plane signs in as (--node; default: zoo, or yours on a Mac)
#   --check              only run the pre-flight checks
set -euo pipefail

REPO="chann44/zoo"
ZOO_HOME="${ZOO_HOME:-/opt/zoo}"
ZOO_VERSION="${ZOO_VERSION:-}"
ADMIN_EMAILS="${ADMIN_EMAILS:-}"
ZOO_DOMAIN="${ZOO_DOMAIN:-}"
KATA_VERSION="${KATA_VERSION:-latest}"
RUNTIME=kata
NODE=0
NODE_KEY=""
CONTROL_PLANE=""
NODE_USER=""
CHECK_ONLY=0
FAILED=0

while [ $# -gt 0 ]; do
    case "$1" in
        --version) ZOO_VERSION="${2#v}"; shift 2 ;;
        --dir) ZOO_HOME="$2"; shift 2 ;;
        --admin-email) ADMIN_EMAILS="$2"; shift 2 ;;
        --domain) ZOO_DOMAIN="$2"; shift 2 ;;
        --runc) RUNTIME=runc; shift ;;
        --node) NODE=1; shift ;;
        --key) NODE_KEY="$2"; shift 2 ;;
        --control-plane) CONTROL_PLANE="${2%/}"; shift 2 ;;
        --user) NODE_USER="$2"; shift 2 ;;
        --check) CHECK_ONLY=1; shift ;;
        -h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

DOCS="https://github.com/$REPO#add-a-server"
[ "$(id -u)" -eq 0 ] || die "run as root: curl -fsSL .../install.sh | sudo bash"

# Pre-flight checks: each prints a line; a failed one stops the install after all have run.

ok() { printf '  \033[32mok\033[0m    %s\n' "$*"; }
note() { printf '  \033[33mnote\033[0m  %s\n' "$*"; }
fail() { printf '  \033[31mfail\033[0m  %s\n' "$*"; FAILED=1; }
need_disk() { # PATH GB
    local free
    free=$(df -Pk "$1" | awk 'NR==2 {print int($4 / 1048576)}')
    if [ "$free" -ge "$2" ]; then ok "${free} GB free on $1"; else fail "${free} GB free on $1, needs $2 GB"; fi
}
need_memory() { # GB_TOTAL MIN RECOMMENDED
    if [ "$1" -lt "$2" ]; then fail "${1} GB of memory, needs $2 GB"
    elif [ "$1" -lt "$3" ]; then note "${1} GB of memory; $3 GB or more runs more sandboxes at once"
    else ok "${1} GB of memory"; fi
}
reach_control_plane() {
    if [ -z "$CONTROL_PLANE" ]; then note "no --control-plane given, skipped the reachability check"
    elif curl -fsS --max-time 10 -o /dev/null "$CONTROL_PLANE/healthz"; then ok "control plane reachable at $CONTROL_PLANE"
    else note "can't reach $CONTROL_PLANE from here; the control plane must still reach this machine over SSH"; fi
}
preflight_done() {
    if [ "$FAILED" = 1 ]; then die "pre-flight checks failed, nothing was installed. See $DOCS"; fi
    if [ "$CHECK_ONLY" = 1 ]; then say "Pre-flight checks passed"; exit 0; fi
}

authorize() { # USER HOME GROUP
    [ -n "$NODE_KEY" ] || die "--node needs --key, the control plane's SSH public key (copy the command from Add server)"
    mkdir -p "$2/.ssh"
    touch "$2/.ssh/authorized_keys"
    grep -qxF "$NODE_KEY" "$2/.ssh/authorized_keys" || printf '%s\n' "$NODE_KEY" >> "$2/.ssh/authorized_keys"
    chown -R "$1:$3" "$2/.ssh"
    chmod 700 "$2/.ssh"
    chmod 600 "$2/.ssh/authorized_keys"
}

joined() { # PLATFORM USER IP RUNS
    local host_key line
    host_key=$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)
    line=$(printf '{"platform":"%s","name":"%s","docker_url":"ssh://%s@%s","bind_address":"%s","host_key":"%s"}' \
        "$1" "$(hostname -s)" "$2" "$3" "$3" "$host_key" | base64 | tr -d '\n')
    say "This machine is ready"
    cat <<EOF

  It can run: $4

  In the dashboard, open Servers > Add server and paste this join line:

  zoo-join:$line

  The control plane reaches this machine at ssh://$2@$3. If it should use another address, edit it there.
EOF
}

# macOS: a node for macOS sandboxes, and Linux ones when Docker Desktop is installed

if [ "$(uname -s)" = Darwin ]; then
    [ "$NODE" = 1 ] || die "the control plane runs on Linux. To run sandboxes on this Mac, open Servers > Add server > Mac in your dashboard and run the command it shows."
    NODE_USER=${NODE_USER:-${SUDO_USER:-}}
    [ -n "$NODE_USER" ] && [ "$NODE_USER" != root ] || die "run this with sudo from the account that will own the VMs, or pass --user"
    home=$(dscl . -read "/Users/$NODE_USER" NFSHomeDirectory | awk '{print $2}')
    say "Checking this Mac"
    if [ "$(uname -m)" = arm64 ]; then ok "Apple Silicon"; else fail "Intel Mac: macOS VMs need Apple Silicon (Virtualization.framework restores macOS only on arm64)"; fi
    major=$(sw_vers -productVersion | cut -d. -f1)
    if [ "$major" -ge 13 ]; then ok "macOS $(sw_vers -productVersion)"; else fail "macOS $(sw_vers -productVersion), needs 13 or later"; fi
    need_disk "$home" 80
    need_memory $(( $(sysctl -n hw.memsize) / 1073741824 )) 16 32
    reach_control_plane
    if [ -x /usr/local/bin/docker ] || [ -x /opt/homebrew/bin/docker ]; then ok "Docker found: this Mac can also run Linux sandboxes"
    else note "no Docker: install Docker Desktop to also run Linux sandboxes here"; fi
    preflight_done

    if ! nc -z 127.0.0.1 22 2>/dev/null; then
        say "Turning on Remote Login"
        systemsetup -setremotelogin on >/dev/null 2>&1 \
            || die "turn on Remote Login in System Settings > General > Sharing, then run this again"
    fi
    # SSH sessions get a bare PATH; zoovm and docker live in /usr/local/bin or /opt/homebrew/bin
    mkdir -p /etc/ssh/sshd_config.d
    printf 'Match User %s\n    SetEnv PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin\n' "$NODE_USER" \
        > /etc/ssh/sshd_config.d/100-zoo.conf
    launchctl kickstart -k system/com.openssh.sshd >/dev/null 2>&1 || true
    authorize "$NODE_USER" "$home" staff

    if [ -z "$ZOO_VERSION" ]; then
        ZOO_VERSION=$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest" | sed 's#.*/tag/v##')
    fi
    say "Installing zoovm $ZOO_VERSION"
    mkdir -p /usr/local/bin
    curl -fsSL "https://github.com/$REPO/releases/download/v$ZOO_VERSION/zoovm-macos-arm64.tar.gz" | tar -xz -C /usr/local/bin
    chmod 755 /usr/local/bin/zoovm

    runs="macOS sandboxes"
    if [ -x /usr/local/bin/docker ] || [ -x /opt/homebrew/bin/docker ]; then runs="macOS and Linux sandboxes"; fi
    ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname)
    joined macos "$NODE_USER" "$ip" "$runs"
    echo "  Then build its base macOS VM from the server's page; it restores macOS from Apple's IPSW."
    exit 0
fi

[ "$(uname -s)" = Linux ] || die "unsupported OS $(uname -s). On Windows, use the PowerShell command from Servers > Add server > Windows."
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

say "Checking this machine"
need_disk / 20
need_memory $(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1048576 )) 4 8
if [ -e /dev/kvm ]; then ok "KVM: sandboxes run in their own VMs (Kata)"
elif [ "$RUNTIME" = runc ]; then note "no KVM; --runc given, so sandboxes share the host kernel"
else note "no KVM: sandboxes will share the host kernel (runc). Use bare metal or nested virtualization for VM isolation"; fi
if [ "$NODE" = 1 ]; then
    reach_control_plane
else
    zoo_running=$(docker compose -p zoo ps -q 2>/dev/null || true)
    for port in 3000 8000; do
        if [ -z "$zoo_running" ] && ss -ltnH "sport = :$port" 2>/dev/null | grep -q .; then fail "port $port is in use"
        else ok "port $port free"; fi
    done
    if curl -fsS --max-time 10 -o /dev/null https://registry-1.docker.io/v2/ -w '' 2>/dev/null || [ $? -eq 22 ]; then ok "Docker Hub reachable"
    else fail "can't reach Docker Hub to pull images"; fi
fi
preflight_done

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

if [ "$NODE" = 1 ]; then
    NODE_USER=${NODE_USER:-zoo}
    id "$NODE_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$NODE_USER"
    usermod -aG docker "$NODE_USER"
    command -v sshd >/dev/null || apt-get install -y -qq openssh-server
    systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true
    authorize "$NODE_USER" "$(getent passwd "$NODE_USER" | cut -d: -f6)" "$NODE_USER"
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    joined linux "$NODE_USER" "${ip:-$(hostname)}" "Linux sandboxes ($RUNTIME)"
    exit 0
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
    # the key the control plane signs in to Mac, Windows and Linux servers with
    mkdir -p ssh
    [ -f ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N '' -C zoo-control-plane -f ssh/id_ed25519
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
ZOO_SSH_DIR=$ZOO_HOME/ssh
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
