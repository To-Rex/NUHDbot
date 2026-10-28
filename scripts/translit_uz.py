"""Uzbek Cyrillic -> Latin (1995 standard, ASCII apostrophes) transliterator.

    uv run python -m scripts.translit_uz app/locales/uz app/locales/uzl

Converts every *.json in the source folder into the target folder (values only, keys untouched).
Latin text, digits, HTML tags and {placeholders} pass through unchanged. Idempotent.
"""
import json
import re
import sys
from pathlib import Path

VOWELS_CYR = set("аеёиоуэюяўАЕЁИОУЭЮЯЎ")

# single letters
SINGLE = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "x", "ҳ": "h", "қ": "q", "э": "e", "ь": "", "ъ": "'", "ы": "i",
}
# letters that become two Latin letters (case handled specially)
DIGRAPH = {"ё": "yo", "ю": "yu", "я": "ya", "ч": "ch", "ш": "sh", "щ": "sh", "ў": "o'", "ғ": "g'"}

# Systematic word-level fixes applied after transliteration (proper nouns, loan words).
FIXES = {
    # proper nouns (transliterated form -> accepted Latin spelling)
    "Shenchjen": "Shenzhen", "Shenchjenga": "Shenzhenga", "Shenchjenda": "Shenzhenda",
    "Guanchjou": "Guangzhou", "Guanchjouda": "Guangzhouda", "Guanchjoudan": "Guangzhoudan", "Guanchjouga": "Guangzhouga",
    "Ivu": "Yiwu", "Ivuga": "Yiwuga", "Ivuda": "Yiwuda",
    # Russian loan "серийный рақам" -> natural Uzbek Latin "seriya raqami"
    "seriyniy raqamlar": "seriya raqamlari", "Seriyniy raqamlar": "Seriya raqamlari",
    "seriyniy raqamlari": "seriya raqamlari", "Seriyniy raqamlari": "Seriya raqamlari",
    "seriyniy raqami": "seriya raqami", "Seriyniy raqami": "Seriya raqami",
    "seriyniy raqam": "seriya raqami", "Seriyniy raqam": "Seriya raqami",
    "seriyniy": "seriya", "Seriyniy": "Seriya",
    # cargo-code example intentionally contains Cyrillic letters (spec 15.05)
    "750VV": "750ВВ",
}
# Phrases that must stay exactly as in the source (language names shown in their own script)
KEEP_EXACT = {"Ўзбекча (кирилл)", "Русский"}

_TOKEN_RE = re.compile(r"(<[^>]*>|\{[^}]*\}|https?://\S+|@\w+)")


def _is_upper(ch: str) -> bool:
    return ch.isalpha() and ch == ch.upper() and ch != ch.lower()


def _case_like(latin: str, src: str, next_ch: str | None, prev_ch: str | None = None) -> str:
    """Apply the Cyrillic letter's case to a 1- or 2-letter Latin output."""
    if not _is_upper(src):
        return latin
    if len(latin) <= 1:
        return latin.upper()
    # ALL-CAPS context: next letter uppercase, or end of word after an uppercase letter -> "SH"; else "Sh"
    if next_ch is not None and next_ch.isalpha():
        return latin.upper() if _is_upper(next_ch) else latin[0].upper() + latin[1:]
    if prev_ch is not None and prev_ch.isalpha() and _is_upper(prev_ch):
        return latin.upper()
    return latin[0].upper() + latin[1:]


def _translit_segment(text: str) -> str:
    out: list[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        low = ch.lower()
        prev = text[i - 1] if i > 0 else None
        nxt = text[i + 1] if i + 1 < n else None
        if low == "е":
            # ye at word start or after a vowel / ь / ъ, else e
            if prev is None or not prev.isalpha() or prev in VOWELS_CYR or prev.lower() in ("ь", "ъ"):
                out.append(_case_like("ye", ch, nxt, prev))
            else:
                out.append("E" if _is_upper(ch) else "e")
        elif low == "ц":
            # ts at word start / after a vowel, s after a consonant (auksion, litsey)
            if prev is None or not prev.isalpha() or prev in VOWELS_CYR:
                out.append(_case_like("ts", ch, nxt, prev))
            else:
                out.append("S" if _is_upper(ch) else "s")
        elif low in DIGRAPH:
            out.append(_case_like(DIGRAPH[low], ch, nxt, prev))
        elif low in SINGLE:
            lat = SINGLE[low]
            out.append(lat.upper() if _is_upper(ch) and lat else lat)
        else:
            out.append(ch)
    return "".join(out)


def _apply_fixes(text: str) -> str:
    for wrong, right in FIXES.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text)
    return text


def translit(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    if text in KEEP_EXACT:
        return text
    parts = _TOKEN_RE.split(text)
    result = "".join(p if _TOKEN_RE.fullmatch(p) else _translit_segment(p) for p in parts)
    return _apply_fixes(result)


def translit_json(obj):
    if isinstance(obj, dict):
        return {k: translit_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [translit_json(v) for v in obj]
    if isinstance(obj, str):
        return translit(obj)
    return obj


def convert_folder(src: Path, dst: Path) -> list[Path]:
    dst.mkdir(parents=True, exist_ok=True)
    written = []
    for f in sorted(src.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        out = dst / f.name
        out.write_text(json.dumps(translit_json(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(out)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    for p in convert_folder(Path(argv[1]), Path(argv[2])):
        print("wrote", p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
