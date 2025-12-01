#!/bin/sh
set -e

# Ensure data directory is writable by appuser (covers fresh named volumes)
mkdir -p /data
chown appuser:appuser /data

# Prime raid data if missing or stale (>24h)
DATA_FILE="${RAID_DATA_PATH:-/data/available_raids.json}"
mod_ts=0
if [ -f "$DATA_FILE" ]; then
    mod_ts=$(stat -c %Y "$DATA_FILE" 2>/dev/null || stat -f %m "$DATA_FILE" 2>/dev/null || echo 0)
fi
now_ts=$(date +%s)
age=$((now_ts - mod_ts))
if [ ! -f "$DATA_FILE" ] || [ "$age" -ge 86400 ]; then
    echo "Priming raid data to ${DATA_FILE} (age: ${age}s)"
    su -s /bin/sh -c "python /app/availableraids.py --output \"$DATA_FILE\"" appuser || echo "Warning: initial raid fetch failed"
fi

# Start cron in the background
cron

# Run the web app as the non-root user
exec su -s /bin/sh -c "gunicorn -w 2 -b 0.0.0.0:8000 raid:application" appuser
