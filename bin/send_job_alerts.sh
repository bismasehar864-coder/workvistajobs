#!/bin/sh
#
# Daily job alert digest, for the scheduler.
#
# Wrapped in a script rather than inlined into the launchd plist so the
# command can be read and changed without XML-escaping shell operators
# (`2>&1` alone is enough to make a plist invalid), and so it can be run
# by hand exactly as the scheduler runs it:
#
#     ./bin/send_job_alerts.sh
#
# Loaded by ~/Library/LaunchAgents/com.workvista.jobalerts.plist.
# See guidebook/13-job-alerts.md.

set -eu

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_DIR"

mkdir -p logs

{
    /bin/date '+=== %Y-%m-%d %H:%M:%S ==='
    venv311/bin/python manage.py send_job_alerts
} >> logs/job_alerts.log 2>&1
