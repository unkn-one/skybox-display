# syntax=docker/dockerfile:1
FROM debian:bookworm

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3-dev python3-venv python3-pip git dpkg-dev build-essential make ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Helpful for dynamic versioning in local docker builds
RUN pip3 install --no-cache-dir -U setuptools-scm tomli || true

WORKDIR /work
CMD ["make","deb"]
