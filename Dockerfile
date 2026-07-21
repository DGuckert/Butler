FROM python:3.11-slim

# ffmpeg is required by yt-dlp's audio extraction postprocessor.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data that should outlive the container: downloaded audio, both SQLite
# databases, and the songs metadata cache. All three paths are pointed
# here by the environment variables set below, so a single volume mount
# on /data is enough to persist everything.
RUN mkdir -p /data/music
ENV MUSIC_DIR=/data/music \
    DATABASE_URL=/data/butler.db \
    SONGS_DB_PATH=/data/songs_meta.db

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8080/ || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
