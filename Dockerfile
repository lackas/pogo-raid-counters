FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos "" appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY raid.py availableraids.py ./
COPY cron ./cron/

# Install cron job for the app user
RUN crontab -u appuser /app/cron/availableraids

# Ensure app files are readable by appuser
RUN chown -R appuser:appuser /app

# Entrypoint starts cron, then the web server
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
