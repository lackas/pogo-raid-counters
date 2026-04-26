#!/bin/sh
set -e
cd "$(dirname "$0")"
APP_VERSION=$(git describe --tags --always --dirty 2>/dev/null || echo dev)
docker compose down
docker compose build --build-arg APP_VERSION="$APP_VERSION"
docker compose up -d
