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
unit_template="$deploy_path/deploy/trading-bot.service"
unit_tmp="$(mktemp)"
sed "s|@DEPLOY_PATH@|$deploy_path|g" "$unit_template" > "$unit_tmp"
sudo install -m 0644 "$unit_tmp" /etc/systemd/system/trading-bot.service
rm -f "$unit_tmp"
sudo systemctl daemon-reload
sudo systemctl enable trading-bot.service
sudo systemctl restart trading-bot.service
docker compose up -d --remove-orphans --wait --wait-timeout 240
docker compose ps
systemctl --no-pager --full status trading-bot.service
