# zoo-guest: the in-sandbox agent the API sends tool calls to (see guest/)
FROM --platform=$BUILDPLATFORM golang:1.26-bookworm AS guest
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY guest/go.mod guest/go.sum ./
RUN go mod download
COPY guest/ ./
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -ldflags="-s -w" -o /zoo-guest .

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

COPY --from=guest /zoo-guest /usr/local/bin/zoo-guest
COPY supervisord.conf /etc/supervisor/conf.d/desktop.conf
COPY sandbox-entrypoint.sh /usr/local/bin/sandbox-entrypoint
RUN chmod 755 /usr/local/bin/sandbox-entrypoint

EXPOSE 6080

CMD ["/usr/local/bin/sandbox-entrypoint"]