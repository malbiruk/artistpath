"""Loose transliteration block key (candidate generation only -- NOT clean_str,
NOT shared with Rust, NOT used for search). Folds the common Slavic/Cyrillic
romanization ambiguities so that e.g. 'poshlaia molli' (unidecode of the Cyrillic),
'poshlaya molly', and 'poshlaja molli' collapse to one block. Aggressive on
purpose: it generates merge *candidates*; a graph gate decides actual merges.

Operates on top of clean_str output (ascii, lowercase, single-spaced)."""

# digraph normalisations: collapse the multi-letter romanizations of single
# Cyrillic letters that scribes spell inconsistently (kh/h for х, zh/z for ж, ...)
_DIGRAPHS = (
    ("shch", "sc"), ("sch", "sc"),   # щ
    ("kh", "h"),                       # х  (unidecode -> kh; others h/x)
    ("zh", "z"),                       # ж
    ("tch", "c"), ("ts", "c"), ("ch", "c"),  # ч / ц
)


def translit_key(clean: str) -> str:
    s = clean
    for a, b in _DIGRAPHS:
        s = s.replace(a, b)
    # glide / soft vowels: я=ia/ya/ja, ю=iu/yu/ju, й=i/j/y, ы=y/i  ->  i
    s = s.replace("j", "i").replace("y", "i")
    # collapse runs of the same letter: molli/molly, anna/ana, ll/l
    out: list[str] = []
    for ch in s:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)
