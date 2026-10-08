# A small stand-in for the sandbox images in the Kubernetes driver's tests: the zoo user, whose home (.bashrc from
# useradd) a new home claim gets a copy of, and the tools the driver runs in sandboxes and helpers.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash zoo
CMD ["sleep", "infinity"]
