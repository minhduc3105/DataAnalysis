#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
UV_BIN="$(command -v uv)"
if [[ "$ROOT_DIR" =~ [[:space:]] || "$UV_BIN" =~ [[:space:]] ]]; then
  echo "The service installer needs repository and uv paths without spaces." >&2
  exit 2
fi

CONFIG_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}"
UNIT_DIR="$CONFIG_ROOT/systemd/user"
UNIT_PATH="$UNIT_DIR/vn-music-radar-scheduler.service"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_PATH" <<UNIT
[Unit]
Description=VN Music Radar live collection scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Ho_Chi_Minh
ExecStart=$UV_BIN run --project $ROOT_DIR python $ROOT_DIR/main.py news schedule
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now vn-music-radar-scheduler.service
printf 'Enabled %s\n' "$UNIT_PATH"
