#!/usr/bin/env sh
# Generates the crontab from config/freshness.yaml and runs it with supercronic (logs to stdout).
set -eu
bankrec schedule crontab > /tmp/crontab
echo "worker schedule:"; cat /tmp/crontab
exec supercronic -passthrough-logs /tmp/crontab
