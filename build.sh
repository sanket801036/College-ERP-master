#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

# The policy documents the assistant answers from. Re-running skips what is
# already there, and --embed only touches passages that have no vector yet,
# so a deploy costs nothing once the corpus is in. Skipped without a Gemini
# key: the offline fake would store its own vectors, and a real key never
# replaces a vector that exists. A provider outage must not fail the deploy.
if [ -n "$GEMINI_API_KEY" ]; then
  python manage.py seed_materials --embed || echo 'seed_materials failed; the assistant will refuse until it is re-run'
fi
