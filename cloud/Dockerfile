FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY cloud/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY paths.py db.py part2_outbound.py email_sender.py scheduler.py \
    resume.py gmail_oauth.py run_scheduled_outbound.py /app/

COPY cloud/crontab /etc/cron.d/clay-outbound
RUN chmod 0644 /etc/cron.d/clay-outbound \
    && crontab /etc/cron.d/clay-outbound

COPY cloud/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV CLAY_OUTBOUND_DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

CMD ["/entrypoint.sh"]
