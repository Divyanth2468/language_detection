#!/bin/bash
# ============================================================
#  language_mapping — environment setup
#  Run once: chmod +x setup.sh && ./setup.sh
# ============================================================
set -e
echo "========================================"
echo "  M3U8 Language Mapper -- Setup"
echo "========================================"

# -- 1. Python version check ----------------------------------
PYTHON=$(command -v python3.11 || command -v python3.10 || command -v python3.9 || command -v python3)
if [ -z "$PYTHON" ]; then
  echo "ERROR: Python 3.9+ is required. Install it first."
  exit 1
fi
echo "OK: Using Python: $($PYTHON --version)"

# -- 2. Virtual environment -----------------------------------
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  $PYTHON -m venv venv
fi
source venv/bin/activate
echo "OK: Virtual environment ready"

# -- 3. Pip + build tools — EXACT VERSIONS -------------------
# torch 2.x requires setuptools<82.
# Pinning to <82 satisfies torch AND provides pkg_resources for whisper.
echo "Installing build tools..."
pip install --upgrade pip --quiet
pip install "setuptools>=68,<82" wheel --quiet
echo "OK: Build tools ready (setuptools pinned <82 for torch compatibility)"

# -- 4. FFmpeg check ------------------------------------------
if ! command -v ffmpeg &> /dev/null; then
  echo ""
  echo "WARNING: FFmpeg not found. Install it:"
  echo "    macOS:   brew install ffmpeg"
  echo "    Ubuntu:  sudo apt install ffmpeg"
  echo "    Windows: https://ffmpeg.org/download.html"
  echo ""
else
  echo "OK: FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
fi

# -- 5. Python dependencies -----------------------------------
echo "Installing Python packages (this may take a few minutes)..."

# Step 1: torch first — large download, benefits from isolated install
echo "   [1/3] Installing PyTorch (may take a while)..."
pip install "torch>=2.0.0" --quiet

# Step 2: install whisper directly from GitHub — avoids the PyPI
#         build-from-source path that triggers the pkg_resources error
echo "   [2/3] Installing Whisper from GitHub..."
pip install "git+https://github.com/openai/whisper.git" --quiet

# Step 3: rest of requirements (whisper excluded from requirements.txt)
echo "   [3/3] Installing remaining packages..."
pip install -r requirements.txt --quiet
echo "OK: All packages installed"

# -- 6. Verify whisper import ---------------------------------
python -c "import whisper; print('OK: Whisper import OK')" 2>/dev/null \
  || echo "WARNING: Whisper import check failed -- try: pip install git+https://github.com/openai/whisper.git"

# -- 7. Create .env if missing --------------------------------
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "OK: Created .env from .env.example -- edit it to add your DB credentials"
fi

# -- 8. Folder structure --------------------------------------
mkdir -p output temp logs

echo ""
echo "========================================"
echo "  Setup complete!"
echo ""
echo "  Activate environment:"
echo "    source venv/bin/activate"
echo ""
echo "  Run on a URL:"
echo "    python main.py --url 'https://example.com/stream.m3u8'"
echo ""
echo "  Run on a list of URLs:"
echo "    python main.py --input urls.txt"
echo "========================================"
