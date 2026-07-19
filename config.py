import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

MUSIC_DIR = os.getenv("MUSIC_DIR", str(BASE_DIR / "music"))
SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
DATABASE_URL = os.getenv("DATABASE_URL", "butler.db")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
# Must match a Redirect URI registered in your Spotify dev dashboard.
# Example for LAN: http://dgserver.local:8080/spotify/auth/callback
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "")
