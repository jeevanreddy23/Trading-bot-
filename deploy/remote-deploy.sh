#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_SHA:?DEPLOY_SHA is required}"
repo_url="${REPO_URL:-https://github.com/jeevanreddy23/Trading-bot-.git}"
deploy_path="${DEPLOY_PATH:-/opt/trading-bot}"

if [[ ! -d "$deploy_path/.git" ]]; then
  sudo mkdir -p "$deploy_path"
  sudo chown "$(id -u):$(id -g)" "$deploy_path"
  git clone "$repo_url" "$deploy_path"
fi

cd "$deploy_path"
git fetch --depth=1 origin "$DEPLOY_SHA"
git checkout --detach "$DEPLOY_SHA"

if [[ ! -f .env ]]; then
  echo "Missing $deploy_path/.env; copy .env.example and add VPS-only secrets." >&2
  exit 1
fi

docker compose config --quiet
docker compose build --pull fleet collector monitor
docker compose up -d --remove-orphans
docker compose ps
