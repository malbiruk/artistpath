from unidecode import unidecode


def clean_str(s: str) -> str:
    return " ".join(unidecode(s).strip().lower().split())
