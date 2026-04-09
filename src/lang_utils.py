"""
src/lang_utils.py
─────────────────
Language ID resolution and match status logic.
Single source of truth for all lang ID / name lookups.
"""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    WHISPER_TO_LANG_ID,
    LANG_ID_COVERS_DIALECTS,
    DIALECT_OF,
    LANGUAGE_NAMES,
)

# ── languageMaster ID → name (built from your DB table) ───────────────────
LANG_ID_TO_NAME: dict[int, str] = {
    1: "English",     2: "Assamese",    3: "Bengali",     5: "Dogri",
    6: "Gujarati",    7: "Hindi",       8: "Kannada",     11: "Maithili",
    12: "Malayalam",  13: "Marathi",    14: "Meitei",     15: "Nepali",
    16: "Odia",       17: "Punjabi",    19: "Santali",    20: "Sindhi",
    21: "Tamil",      22: "Telugu",     23: "Urdu",       24: "Arabic",
    27: "Czech",      28: "Danish",     29: "Dutch",      30: "Finnish",
    31: "Filipino",   32: "French",     33: "German",     34: "Greek",
    35: "Hebrew",     36: "Hungarian",  37: "Indonesian",  38: "Italian",
    39: "Japanese",   40: "Korean",     41: "Spanish",    42: "Russian",
    43: "Bhojpuri",   44: "Portuguese", 45: "Polish",     46: "Quechua",
    47: "Aymara",     48: "Guarani",    49: "Malay",      50: "Mandarin",
    51: "Cantonese",  52: "Turkish",    53: "Kurdish",    54: "Circassian",
    55: "Armenian",   56: "Hausa",      57: "Swahili",    58: "Amharic",
    61: "Tamazight",  62: "Khoe",       63: "Yoruba",     64: "Zulu",
    65: "Ukrainian",  66: "Vietnamese", 67: "Javanese",   68: "Thai",
    69: "Persian/Farsi", 70: "Burmese", 71: "Pashto",    72: "Sinhala",
    73: "Khmer",      74: "Uzbek",      75: "Kazakh",     76: "Azerbaijani",
    77: "Romanian",   78: "Somali",     79: "Igbo",       80: "Wolof",
    81: "Afrikaans",  82: "Tigrinya",   83: "Swedish",    84: "Norwegian",
    85: "Lao",        86: "Shona",
}


def whisper_code_to_lang_id(iso_code: str) -> int | None:
    """Convert Whisper ISO code → languageMaster ID. Returns None if unmapped."""
    return WHISPER_TO_LANG_ID.get(iso_code)


def lang_ids_to_names(lang_ids: list[int]) -> str:
    """Convert list of lang IDs → comma-separated names. e.g. [7,22] → 'Hindi, Telugu'"""
    return ", ".join(LANG_ID_TO_NAME.get(i, f"unknown({i})") for i in lang_ids)


def resolve_match_status(
    current_lang_ids: list[int],
    detected_lang_id: int | None,
) -> str:
    """
    Compare existing DB language tag against what Whisper detected.

    Returns one of:
        match         — detected lang is in the video's current_lang_ids
        dialect_match — detected lang is the parent of a dialect in current_lang_ids
        mismatch      — detected lang not in current_lang_ids and not a dialect
        untagged      — video had no language tag in DB (current_lang_ids is empty)
        unmapped      — Whisper detected a language we have no lang ID for
        error         — detection failed
    """
    if detected_lang_id is None:
        return "unmapped"

    if not current_lang_ids:
        return "untagged"

    # Direct match
    if detected_lang_id in current_lang_ids:
        return "match"

    # Dialect match — e.g. detected Hindi (7), video tagged Bhojpuri (43)
    dialects_covered = LANG_ID_COVERS_DIALECTS.get(detected_lang_id, set())
    if dialects_covered & set(current_lang_ids):
        return "dialect_match"

    # Reverse — video tagged a dialect, detected its parent
    for cid in current_lang_ids:
        parent = DIALECT_OF.get(cid)
        if parent is not None and parent == detected_lang_id:
            return "dialect_match"

    return "mismatch"
