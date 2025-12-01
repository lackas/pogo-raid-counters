#!/bin/sh
set -e

# Ensure data directory is writable by appuser (covers fresh named volumes)
mkdir -p /data
chown appuser:appuser /data

# Start cron in the background
cron

# Run the web app as the non-root user
exec su -s /bin/sh -c "gunicorn -w 2 -b 0.0.0.0:8000 raid:application" appuser
