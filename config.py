"""
config.py — Central configuration for the M3U8 Language Mapper.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"

for _d in (TEMP_DIR, OUTPUT_DIR, LOG_DIR):
    _d.mkdir(exist_ok=True)

# ── Whisper ────────────────────────────────────────────────────────────────
WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "small")
WHISPER_MODELS: list = ["tiny", "base", "small", "medium", "large"]

WHISPER_MODEL_DESCRIPTIONS = {
    "tiny": "Fastest, least accurate  (~1 GB VRAM)",
    "base": "Fast, good accuracy      (~1 GB VRAM)",
    "small": "Balanced                 (~2 GB VRAM)",
    "medium": "High accuracy, slower    (~5 GB VRAM)",
    "large": "Best accuracy, slowest   (~10 GB VRAM)",
}

# ── Sampling ───────────────────────────────────────────────────────────────
TS_SAMPLE_COUNT: int = int(os.getenv("TS_SAMPLE_COUNT", 10))
AUDIO_CLIP_SECONDS: int = 120
AUDIO_OFFSET_SECONDS: int = 0

# ── Networking ─────────────────────────────────────────────────────────────
REQUEST_TIMEOUT: int = 30
REQUEST_HEADERS: dict = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Output ─────────────────────────────────────────────────────────────────
OUTPUT_CSV: Path = BASE_DIR / os.getenv("OUTPUT_CSV", "output/results.csv")

CSV_COLUMNS = [
    "url",
    "detected_language",
    "language_name",
    "confidence",
    "whisper_model",
    "ts_sampled",
    "audio_duration_s",
    "status",
    "error",
    "timestamp",
]

# ── Dashboard ──────────────────────────────────────────────────────────────
GOOGLE_SHEET_URL: str = os.getenv("GOOGLE_SHEET_URL", "")

# ── DB ─────────────────────────────────────────────────────────────────────
DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: int = int(os.getenv("DB_PORT", 3306))
DB_NAME: str = os.getenv("DB_NAME", "lyk_production")
DB_USER: str = os.getenv("DB_USER", "LYK_admin")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "LYKstage#2025#")

# ── Whisper ISO 639-1 → languageMaster ID ─────────────────────────────────
WHISPER_TO_LANG_ID: dict = {
    "en": 1,
    "as": 2,
    "bn": 3,
    "gu": 6,
    "hi": 7,
    "kn": 8,
    "ml": 12,
    "mr": 13,
    "ne": 15,
    "or": 16,
    "pa": 17,
    "ta": 21,
    "te": 22,
    "ur": 23,
    "ar": 24,
    "cs": 27,
    "da": 28,
    "nl": 29,
    "fi": 30,
    "tl": 31,
    "fr": 32,
    "de": 33,
    "el": 34,
    "he": 35,
    "hu": 36,
    "id": 37,
    "it": 38,
    "ja": 39,
    "ko": 40,
    "es": 41,
    "ru": 42,
    "pt": 44,
    "pl": 45,
    "ms": 49,
    "zh": 50,
    "tr": 52,
    "hy": 55,
    "sw": 57,
    "uk": 65,
    "vi": 66,
    "th": 68,
    "fa": 69,
    "my": 70,
    "si": 72,
    "km": 73,
    "uz": 74,
    "kk": 75,
    "ro": 77,
    "af": 81,
    "sv": 83,
    "no": 84,
    "lo": 85,
}

# ── Dialect mapping ────────────────────────────────────────────────────────
# Languages your DB has that Whisper cannot detect directly.
# Maps your languageMaster ID → parent lang ID Whisper detects instead.
DIALECT_OF: dict = {
    43: 7,  # Bhojpuri  → Hindi
    11: 7,  # Maithili  → Hindi
    5: 7,  # Dogri     → Hindi
    20: 23,  # Sindhi    → Urdu
    14: None,  # Meitei    → unmappable
    19: None,  # Santali   → unmappable
}

# Auto-built reverse map: detected lang_id → dialect IDs it covers
LANG_ID_COVERS_DIALECTS: dict = {}
for _d, _p in DIALECT_OF.items():
    if _p is not None:
        LANG_ID_COVERS_DIALECTS.setdefault(_p, set()).add(_d)

# ── Language name map (ISO 639-1 → human name) ────────────────────────────
LANGUAGE_NAMES: dict = {
    "af": "Afrikaans",
    "ar": "Arabic",
    "as": "Assamese",
    "bn": "Bengali",
    "bs": "Bosnian",
    "ca": "Catalan",
    "cs": "Czech",
    "cy": "Welsh",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "gl": "Galician",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "hy": "Armenian",
    "id": "Indonesian",
    "is": "Icelandic",
    "it": "Italian",
    "ja": "Japanese",
    "ka": "Georgian",
    "kk": "Kazakh",
    "km": "Khmer",
    "kn": "Kannada",
    "ko": "Korean",
    "lo": "Lao",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "ml": "Malayalam",
    "mr": "Marathi",
    "ms": "Malay",
    "mt": "Maltese",
    "my": "Burmese",
    "ne": "Nepali",
    "nl": "Dutch",
    "no": "Norwegian",
    "or": "Odia",
    "pa": "Punjabi",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sq": "Albanian",
    "sr": "Serbian",
    "sv": "Swedish",
    "sw": "Swahili",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tl": "Filipino",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "zh": "Chinese",
    "zu": "Zulu",
}
