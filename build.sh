#!/usr/bin/env bash
#
# Render build step. Runs on every deploy, before the start command.
# See guidebook/14-deploying.md.

set -o errexit

pip install -r requirements.txt

# Not a pip package - see requirements.txt.
python -m spacy download en_core_web_sm

python manage.py collectstatic --no-input

# A no-op against a database loaded from mysql/01_schema.sql, which
# already carries the migration history; applies any newer ones.
python manage.py migrate --no-input