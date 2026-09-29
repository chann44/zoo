#!/bin/sh
# Prepares the macOS base VM for Zoo. Run once inside the guest, in Terminal, as the admin user:
#   sh guest-setup.sh "<API public key>" "<this user's password>"
set -e
KEY="$1"
PASSWORD="$2"
if [ -z "$KEY" ] || [ -z "$PASSWORD" ]; then
    echo "usage: sh guest-setup.sh \"<ssh public key>\" \"<password>\"" >&2
    exit 1
fi
ME="$(whoami)"

echo "$PASSWORD" | sudo -S -v
echo "$ME ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/zoo >/dev/null
sudo chmod 440 /etc/sudoers.d/zoo

# Remote Login, so Zoo can run commands and move files.
sudo launchctl enable system/com.openssh.sshd
sudo launchctl bootstrap system /System/Library/LaunchDaemons/ssh.plist 2>/dev/null || true
mkdir -p ~/.ssh && chmod 700 ~/.ssh
grep -qxF "$KEY" ~/.ssh/authorized_keys 2>/dev/null || echo "$KEY" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# Log straight into the desktop on boot and never sleep or lock.
sudo sysadminctl -autologin set -userName "$ME" -password "$PASSWORD"
sudo pmset -a sleep 0 displaysleep 0 disksleep 0
defaults -currentHost write com.apple.screensaver idleTime 0
sudo defaults write /Library/Preferences/com.apple.screensaver loginWindowIdleTime 0
sysadminctl -screenLock off -password "$PASSWORD" 2>/dev/null || true

echo "done. Now grant Accessibility to /usr/libexec/sshd-keygen-wrapper (see macos/README.md), then shut down."
