#!/usr/bin/env bash
set -euo pipefail

args=(python run.py --config config.live.yaml)
if [[ "${LIVE_TRADING_ACK:-}" == "I_UNDERSTAND_THE_RISKS" ]]; then
  echo "[entrypoint] explicit live acknowledgement detected"
  args+=(--live)
else
  echo "[entrypoint] live acknowledgement absent; running the Kraken profile in paper mode"
fi

exec "${args[@]}"
