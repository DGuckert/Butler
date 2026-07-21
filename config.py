import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# `or` rather than getenv's own default: an empty string in .env (which
# .env.example ships, so people leave it blank on purpose) should fall
# through to the default too, not be treated as "explicitly set to ''".
MUSIC_DIR = os.getenv("MUSIC_DIR") or str(BASE_DIR / "music")
SECRET_KEY = os.getenv("SECRET_KEY") or "changeme"
DATABASE_URL = os.getenv("DATABASE_URL") or "butler.db"
SONGS_DB_PATH = os.getenv("SONGS_DB_PATH") or str(BASE_DIR / "songs_meta.db")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
# Must match a Redirect URI registered in your Spotify dev dashboard.
# Example for LAN: http://dgserver.local:8080/spotify/auth/callback
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "")
