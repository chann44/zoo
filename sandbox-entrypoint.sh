#!/bin/sh
# Stores the API's x11vnc password (ZOO_VNC_PASSWORD) where x11vnc reads it, then starts the desktop with the
# variable removed so nothing else in the sandbox inherits it. Without one, x11vnc gets a random password nobody knows.
set -e
x11vnc -storepasswd "${ZOO_VNC_PASSWORD:-$(head -c 32 /dev/urandom | base64)}" /etc/x11vnc.pass >/dev/null
chown zoo /etc/x11vnc.pass
chmod 600 /etc/x11vnc.pass
unset ZOO_VNC_PASSWORD
exec /usr/bin/supervisord -n
