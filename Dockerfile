# syntax=docker/dockerfile:1
FROM python:3.10-slim

# Unbuffered so container logs appear as they happen rather than in blocks -
# the app writes everything to stdout for exactly this reason.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg2-binary ships its own libpq, so only the client library is needed at
# runtime - no build toolchain.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

# Requirements first, so a code change does not reinstall every dependency.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Collected at build time rather than on boot: the files never change after the
# image is built, and whitenoise serves them straight from the image.
# No database is touched by collectstatic, so no connection details are needed.
RUN SECRET_KEY=build-only python manage.py collectstatic --no-input

# Not root. A compromised web process should not own the filesystem it runs on.
RUN useradd --create-home --uid 1000 app \
 && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["gunicorn", "CollegeERP.wsgi:application", "--bind", "0.0.0.0:8000"]
