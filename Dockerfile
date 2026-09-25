FROM debian:bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    xfce4 \
    xfce4-terminal \
    xvfb \
    x11vnc \
    novnc \
    supervisor \
    firefox-esr \
    dbus-x11 \
    imagemagick \
    xdotool \
    iptables \
    wmctrl \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash zoo

COPY supervisord.conf /etc/supervisor/conf.d/desktop.conf

EXPOSE 6080

CMD ["/usr/bin/supervisord", "-n"]