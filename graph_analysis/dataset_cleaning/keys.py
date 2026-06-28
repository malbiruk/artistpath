"""Normalization keys used to generate cleaning candidates.

Two independent keys over an artist name:

- clean_str  : phonetic fold (unidecode + lower + collapse). This is the EXACT
               key the serving code uses (core/src/string_normalization.rs). It
               folds transliterations *by sound* -> catches "Molchat Doma" vs
               "Молчат Дома" only when the human romanization matches unidecode.
- skeleton   : visual fold (NFKD strip-accents + homoglyph map). Catches
               look-alike spoofs that clean_str MISSES, e.g. a Cyrillic "с"
               (es, unidecode -> "s") used in place of a Latin "c".

`mixed_script_name` flags names with a single token drawn from >1 script — a
near-certain homoglyph spoof/typo, usable as a standalone signal.
"""

import re
import string
import unicodedata

from unidecode import unidecode

# --- phonetic key (mirror of clean_str in Python postprocessing + Rust) ------


def clean_str(s: str) -> str:
    return " ".join(unidecode(s).strip().lower().split())


# --- visual key (homoglyph skeleton) -----------------------------------------

# Curated confusable map: characters that *look like* a Latin letter but live in
# another script, mapped to that Latin letter. Covers the dominant real case in
# a Last.fm dataset (Cyrillic / Greek letters substituted into Latin names).
# Not a full Unicode TR39 table — production should swap in `confusables` — but
# enough to estimate blast radius and validate the hypothesis. Keys are stored
# lowercased; uppercase is folded by lowercasing before lookup.
_HOMOGLYPHS: dict[str, str] = {
    # Cyrillic -> Latin
    "а": "a", "в": "b", "е": "e", "ѕ": "s", "і": "i", "ј": "j", "к": "k",
    "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t", "у": "y",
    "х": "x", "ԁ": "d", "ԛ": "q", "ԝ": "w", "г": "r", "ӏ": "i", "ё": "e",
    # Greek -> Latin
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "μ": "u",
    "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ζ": "z",
    "γ": "y", "π": "n",
}


def skeleton(s: str) -> str:
    """Visual normal form: strip accents (NFKD), fold confusables to Latin,
    lowercase, drop punctuation, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", s)
    out: list[str] = []
    for ch in nfkd:
        if unicodedata.combining(ch):
            continue
        lo = ch.lower()
        folded = _HOMOGLYPHS.get(lo, lo)
        if folded.isalnum() or folded.isspace():
            out.append(folded)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


# --- mixed-script detection --------------------------------------------------


def _char_script(ch: str) -> str | None:
    o = ord(ch)
    if ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
        return "Latin"
    if 0x0400 <= o <= 0x052F:
        return "Cyrillic"
    if 0x0370 <= o <= 0x03FF:
        return "Greek"
    return None


def mixed_script_name(s: str) -> bool:
    """True if any single whitespace-token mixes letters from >1 script."""
    for tok in s.split():
        scripts: set[str] = set()
        for ch in tok:
            sc = _char_script(ch)
            if sc:
                scripts.add(sc)
        if len(scripts) > 1:
            return True
    return False


# --- feature / collab tokens -------------------------------------------------

# Connector tokens that glue collaborating artists together. Used as a CONFIDENCE
# signal (token coverage), never as a hard gate — features are barely normalized.
CONNECTORS: frozenset[str] = frozenset(
    {
        "feat", "feats", "ft", "featuring", "feature", "with", "w",
        "vs", "versus", "x", "and", "n", "et", "con", "y",
        "&", "+", ",", "/", "|", "·", "×",
    }
)

_PUNCT = string.punctuation


def strip_punct(tok: str) -> str:
    return tok.strip(_PUNCT)


def is_connector(tok: str) -> bool:
    return tok in CONNECTORS or strip_punct(tok) in CONNECTORS


# --- delimiter segmentation (popularity-blind collab detection) --------------

# Word split-markers: only the one standardized feature word + its abbreviations.
# The ambiguous ones (x, vs, presents, prod, and, with, n, e, y...) are gone on
# purpose -- they're arbitrary vocabulary. These just mark WHERE to split; the
# keep/delete decision is made by graph centrality, not by which word joined.
STRONG_CONNECTORS: frozenset[str] = frozenset({"feat", "ft", "feats", "featuring", "feature"})
# WEAK: word-level connectors are DISABLED — "and"/"n"/"with"/"e"/"y" shred real
# band names (Florence and the Machine, Guns N' Roses, Earth Wind and Fire). Weak
# collabs are detected only via SYMBOLIC delimiters (, & + / *) in _SPLIT_CHARS,
# which are far less likely to appear mid-name. Re-enable selectively if needed.
WEAK_CONNECTORS: frozenset[str] = frozenset()

# Delimiter characters that split collaborators even when glued to a token
# ("поливокс," -> "поливокс" + split). Note unidecode maps "•" -> "*".
_SPLIT_CHARS = ",/&+*|"
_SPLIT_RE = re.compile(f"([{re.escape(_SPLIT_CHARS)}])")


def segment_name(norm: str) -> tuple[list[str], bool, bool]:
    """Split a normalized name into collaborator segments on connector tokens and
    delimiter chars. Returns (segments, has_strong_connector, has_weak_connector).
    Other punctuation inside a name (e.g. the dot in "last past.") is preserved."""
    segs: list[str] = []
    cur: list[str] = []
    has_strong = False
    has_weak = False

    for tok in norm.split():
        for p in _SPLIT_RE.split(tok):
            if not p:
                continue
            if p in _SPLIT_CHARS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
                has_weak = True
                continue
            core = p.strip(_PUNCT)
            if core in STRONG_CONNECTORS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
                has_strong = True
            elif core in WEAK_CONNECTORS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
                has_weak = True
            else:
                cur.append(p)
    if cur:
        segs.append(" ".join(cur))
    return [s for s in segs if s], has_strong, has_weak
