import re
from typing import Optional

COLORS = {
    # English
    "red": "red", "blue": "blue", "green": "green", "black": "black",
    "white": "white", "yellow": "yellow", "pink": "pink", "orange": "orange",
    "purple": "purple", "grey": "grey", "gray": "grey", "brown": "brown",
    # Hindi
    "laal": "red", "lal": "red", "neela": "blue", "neel": "blue",
    "hara": "green", "kala": "black", "safed": "white", "peela": "yellow",
    "gulabi": "pink", "narangi": "orange",
    # Telugu
    "erupu": "red", "nalla": "black", "telupu": "white", "pasupu": "yellow",
    "paccha": "green", "neelam": "blue",
    # Tamil
    "sivappu": "red", "karuppu": "black", "veluppu": "white",
    # Marathi
    "pivla": "yellow",
}

CATEGORIES = {
    "shirt": "shirt", "tshirt": "tshirt", "t-shirt": "tshirt",
    "t shirt": "tshirt", "t shirts": "tshirt", "kurti": "kurti", "jeans": "jeans",
    "hoodie": "hoodie", "shoe": "shoe", "shoes": "shoe",
    "saree": "saree", "sari": "saree", "lehenga": "lehenga",
    "bag": "bag", "watch": "watch", "trouser": "jeans",
    "pant": "jeans", "jacket": "hoodie",
}

SIZES = {
    "small": "S", "s size": "S", "chota": "S", "chinna": "S",
    "medium": "M", "m size": "M", "madhyam": "M",
    "large": "L", "l size": "L", "bada": "L", "pedda": "L",
    "xl": "XL", "extra large": "XL",
    "xxl": "XXL", "double xl": "XXL",
}

# ── Keyword anchors ────────────────────────────────────────────────────────────
# A number is ONLY extracted as price/quantity when one of these keywords is
# present in the same utterance. Without them, ambiguous spoken numbers are
# ignored — the LLM will ask for clarification instead.

_PRICE_KEYWORDS = r"(price|cost|rate|rupee|rupees|rs|rupay|rupaye|rupayalu|rupai|விலை|बाटा|paisa|selling|mrp)"
_QTY_KEYWORDS   = r"(piece|pieces|pcs|pc|qty|quantity|stock|units|unit|nos|nag|naag|pisi|pisilu|संख्या)"

# Size-like keywords that should NOT be interpreted as prices
_SIZE_KEYWORDS = r"\b(size|siz|saiz)\b"


def _words_to_number(text: str) -> Optional[int]:
    ones = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    }
    tens = {
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    }

    words = text.lower().replace("-", " ").split()

    # "five fifty" → 550, "three twenty" → 320
    if len(words) >= 2:
        if words[0] in ones and words[1] in tens:
            return ones[words[0]] * 100 + tens[words[1]]
        if words[0] in tens and words[1] in ones:
            return tens[words[0]] + ones[words[1]]

    total = 0
    current = 0
    for word in words:
        if word in ones:
            current += ones[word]
        elif word in tens:
            current += tens[word]
        elif word == "hundred":
            current = (current if current > 0 else 1) * 100
        elif word == "thousand":
            current = (current if current > 0 else 1) * 1000
            total += current
            current = 0
        elif word == "lakh":
            current = (current if current > 0 else 1) * 100000
            total += current
            current = 0

    total += current
    return total if total > 0 else None


def extract_fields(text: str) -> dict:
    text_lower = text.lower().strip()

    result = {
        "category": None,
        "color":    None,
        "price":    None,
        "quantity": None,
        "sizes":    [],
    }

    # ── CATEGORY ──────────────────────────────────────────────────────────
    for key, value in CATEGORIES.items():
        if key in text_lower:
            result["category"] = value
            break

    # ── COLOR ─────────────────────────────────────────────────────────────
    for key, value in COLORS.items():
        if re.search(rf"\b{re.escape(key)}\b", text_lower):
            result["color"] = value
            break

    # ── SIZES ─────────────────────────────────────────────────────────────
    found_sizes = []
    for key, value in SIZES.items():
        if key in text_lower:
            found_sizes.append(value)
    result["sizes"] = list(set(found_sizes))

    # ── PRICE ─────────────────────────────────────────────────────────────
    # Strategy 1: digit preceded/followed by price keyword
    price_match = re.search(
        rf"(?:{_PRICE_KEYWORDS}\s*[:=]?\s*(\d{{2,6}})|(\d{{2,6}})\s*{_PRICE_KEYWORDS})",
        text_lower,
    )
    if price_match:
        raw = price_match.group(2) or price_match.group(3)
        if raw:
            result["price"] = int(raw)

    # Strategy 2: spoken number WITH price keyword, NO size keyword before it
    if result["price"] is None:
        has_price_kw = re.search(_PRICE_KEYWORDS, text_lower)
        has_size_kw  = re.search(_SIZE_KEYWORDS, text_lower)
        if has_price_kw and not has_size_kw:
            spoken = _words_to_number(text_lower)
            if spoken and 10 <= spoken <= 99999:
                result["price"] = spoken

    # ── QUANTITY ──────────────────────────────────────────────────────────
    # ONLY extract quantity when an explicit qty keyword is present.
    qty_match = re.search(
        rf"(?:{_QTY_KEYWORDS}\s*[:=]?\s*(\d{{1,5}})|(\d{{1,5}})\s*{_QTY_KEYWORDS})",
        text_lower,
    )
    if qty_match:
        raw = qty_match.group(2) or qty_match.group(3)
        if raw:
            result["quantity"] = int(raw)

    # NOTE: Spoken-number quantity (e.g. "twenty five fifty") is intentionally
    # NOT extracted here without an explicit keyword. The LLM will ask for qty.

    return result