#!/usr/bin/env bash
set -euo pipefail

cd /opt/aussie-agent-fleet
umask 077

if [[ ! -f .env ]]; then
  echo "Missing /opt/aussie-agent-fleet/.env"
  exit 1
fi

mkdir -p state-live
chmod 700 state-live

docker compose build --pull
docker compose run --rm --no-deps fleet \
  python run.py --config config.live.yaml --cycles 1

echo "Preflight complete. No live executor was armed and no order was sent."