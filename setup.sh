#!/bin/bash
# Butler setup script
# Run as: bash setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Butler Setup ==="

# Install deps
pip install -r requirements.txt --break-system-packages

# Create music dir
mkdir -p "$SCRIPT_DIR/music"

# Copy env template if no .env exists yet
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example — edit it before starting Butler."
fi

# Init DB
python3 -c "from database import init_db; init_db(); print('DB OK')"

echo "=== Setup complete ==="
echo "Edit .env, then run: uvicorn main:app --host 0.0.0.0 --port 8080"
