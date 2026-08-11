#!/usr/bin/env bash
set -euo pipefail

repo_dir="${DEPLOY_PATH:-/opt/trading-bot}"
cd "$repo_dir"
umask 077

if [[ ! -f .env ]]; then
  echo "Missing $repo_dir/.env"
  exit 1
fi

docker compose build --pull fleet
docker compose run --rm --no-deps fleet \
  python run.py --config config.live.yaml --cycles 1

echo "Preflight complete. No live executor was armed and no order was sent."
