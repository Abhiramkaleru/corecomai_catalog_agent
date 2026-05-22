"""
app/core/languages.py
──────────────────────────────────────────────────────────────────────────────
SINGLE SOURCE OF TRUTH for all multilingual configuration.

Add a new language here → it works everywhere automatically:
  - Deepgram STT language code
  - Cartesia / Sarvam TTS voice
  - Twilio <Say> voice
  - Greeting message
  - Closing message
  - Required field prompts

Supported language codes (ISO 639-1):
  hi    → Hindi
  te    → Telugu
  ta    → Tamil
  en    → English (Indian)
  mr    → Marathi
  kn    → Kannada
  bn    → Bengali
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LanguageConfig:
    code: str                    # ISO code used internally: "hi", "te", "en"
    name: str                    # Human readable
    deepgram_code: str           # Deepgram language param
    twilio_voice: str            # Twilio <Say> voice name
    twilio_language: str         # Twilio <Say> language attribute
    cartesia_language: str       # Cartesia language param
    sarvam_code: str             # Sarvam AI language_code
    greeting: str                # First thing spoken to seller
    closing: str                 # Said when catalog is saved
    ask_category: str
    ask_color: str
    ask_size: str
    ask_price: str
    ask_quantity: str
    confirm_save: str


LANGUAGES: dict[str, LanguageConfig] = {

    "hi": LanguageConfig(
        code="hi",
        name="Hindi",
        deepgram_code="hi",
        twilio_voice="Polly.Aditi",
        twilio_language="hi-IN",
        cartesia_language="hi",
        sarvam_code="hi-IN",
        greeting="Namaste! Main aapka AI catalog assistant hoon. Apna product describe karein.",
        closing="Shukriya! Aapka product catalog mein save ho gaya.",
        ask_category="Aap kaunsa product add karna chahte hain?",
        ask_color="Is product ka color kya hai?",
        ask_size="Kaunse size available hain? Jaise S, M, L, XL?",
        ask_price="Is product ki selling price kya hai?",
        ask_quantity="Stock mein kitne pieces hain?",
        confirm_save="Theek hai, main save kar raha hoon.",
    ),

    "te": LanguageConfig(
        code="te",
        name="Telugu",
        deepgram_code="te",
        twilio_voice="Polly.Aditi",      # fallback — Twilio has limited Telugu
        twilio_language="hi-IN",          # Twilio fallback voice
        cartesia_language="te",
        sarvam_code="te-IN",
        greeting="Namaskaram! Nenu mee AI catalog assistant ni. Mee product gurinchi cheppandi.",
        closing="Dhanyavadalu! Mee product catalog lo save ayindi.",
        ask_category="Meeru ela product add cheyalanukunnaaru?",
        ask_color="Ee product color emiti?",
        ask_size="Ela sizes available ga unnaayi? S, M, L, XL?",
        ask_price="Ee product selling price enta?",
        ask_quantity="Stock lo enni pieces unnaayi?",
        confirm_save="Sare, nenu save chestunnaanu.",
    ),

    "ta": LanguageConfig(
        code="ta",
        name="Tamil",
        deepgram_code="ta",
        twilio_voice="Polly.Aditi",
        twilio_language="hi-IN",
        cartesia_language="ta",
        sarvam_code="ta-IN",
        greeting="Vanakkam! Naan ungal AI catalog assistant. Ungal product patti sollunga.",
        closing="Nandri! Ungal product catalog-il save aagividdu.",
        ask_category="Eppadi product add pannanum?",
        ask_color="Ee product-in color enna?",
        ask_size="Eppadi sizes available? S, M, L, XL?",
        ask_price="Ee product-in selling price enna?",
        ask_quantity="Stock-il evvalavu pieces irukku?",
        confirm_save="Sari, naan save pannureen.",
    ),

    "en": LanguageConfig(
        code="en",
        name="English (Indian)",
        deepgram_code="en-IN",
        twilio_voice="alice",
        twilio_language="en-IN",
        cartesia_language="en",
        sarvam_code="en-IN",
        greeting="Hello! I am your AI catalog assistant. Please describe your product.",
        closing="Thank you! Your product has been saved to the catalog.",
        ask_category="What type of product would you like to add?",
        ask_color="What color is this product?",
        ask_size="What sizes are available? For example S, M, L, XL?",
        ask_price="What is the selling price of this product?",
        ask_quantity="How many pieces do you have in stock?",
        confirm_save="Got it, saving now.",
    ),

    "mr": LanguageConfig(
        code="mr",
        name="Marathi",
        deepgram_code="mr",
        twilio_voice="Polly.Aditi",
        twilio_language="hi-IN",
        cartesia_language="mr",
        sarvam_code="mr-IN",
        greeting="Namaskar! Mi tumcha AI catalog assistant aahe. Tumcha product sangaa.",
        closing="Dhanyavad! Tumcha product catalog madhye save zala.",
        ask_category="Tumhi konte product add karaychay?",
        ask_color="Ya product cha color konte aahe?",
        ask_size="Konte sizes available aahet? S, M, L, XL?",
        ask_price="Ya product chi selling price kaay aahe?",
        ask_quantity="Stock madhye kiti pieces aahet?",
        confirm_save="Theek aahe, save karto.",
    ),

    "kn": LanguageConfig(
        code="kn",
        name="Kannada",
        deepgram_code="kn",
        twilio_voice="Polly.Aditi",
        twilio_language="hi-IN",
        cartesia_language="kn",
        sarvam_code="kn-IN",
        greeting="Namaskara! Naanu nimma AI catalog assistant. Nimma product bagge heli.",
        closing="Dhanyavaadagalu! Nimma product catalog-alli save aagide.",
        ask_category="Yaava product add maadabekagide?",
        ask_color="Ee product-da color yaavudu?",
        ask_size="Yaavaavu sizes available? S, M, L, XL?",
        ask_price="Ee product-da selling price eshtu?",
        ask_quantity="Stock-alli eshtu pieces ide?",
        confirm_save="Sari, save maaduttiddeeni.",
    ),
}

# Default language when auto-detection fails
DEFAULT_LANGUAGE = "en"


def get_lang(code: str) -> LanguageConfig:
    """Get language config by code. Falls back to English."""
    return LANGUAGES.get(code, LANGUAGES[DEFAULT_LANGUAGE])


def detect_from_deepgram(detected_languages: list[str]) -> str:
    """
    Map Deepgram's detected language codes to our internal codes.
    Deepgram may return "hi-Latn", "en-US", etc. — we normalize.
    """
    if not detected_languages:
        return DEFAULT_LANGUAGE

    raw = detected_languages[0].lower().split("-")[0]   # "hi-Latn" → "hi"

    # Normalize some Deepgram-specific codes
    mapping = {
        "hi": "hi",
        "te": "te",
        "ta": "ta",
        "en": "en",
        "mr": "mr",
        "kn": "kn",
        "bn": "hi",   # Bengali → fallback Hindi (no Bengali TTS yet)
    }
    return mapping.get(raw, DEFAULT_LANGUAGE)
