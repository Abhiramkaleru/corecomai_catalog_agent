# Seller Catalog Voice Agent

AI-powered voice calling agent for Indian sellers. A seller calls a phone number, describes their product in **Hindi, Telugu, Tamil, Marathi, Kannada, or English** — the system transcribes the call, asks follow-up questions, and saves a structured catalog entry to MongoDB automatically.

---

## How It Works

```
Seller calls your Twilio number
          │
          ▼
  POST /api/calls/incoming
  TwiML greets seller in their language
          │
          ▼ WebSocket audio stream
  /ws/call-stream  (call_socket.py)
          │
    ┌─────┴─────┐
    ▼           ▼
 Deepgram    Gemini AI
 (live STT)  (conversation agent)
 auto-detect  asks follow-up questions
 language     in seller's language
    │           │
    └─────┬─────┘
          ▼
    Cartesia TTS
    (speaks reply back to seller)
          │
          ▼
   Call ends → MongoDB
   saves catalog + full transcript
```

---

## Project Structure

```
seller-catalog-agent/
├── main.py                               # FastAPI app — all routers wired here
├── requirements.txt
├── .env.example
└── app/
    ├── core/
    │   ├── config.py                     # All env vars in one place
    │   ├── languages.py                  # Multilingual config (greetings, TTS voices, STT codes)
    │   └── prompts.py                    # All Gemini system prompts
    ├── db/
    │   └── mongo.py                      # MongoDB — save catalogs + call records
    ├── api/routes/
    │   ├── calls.py                      # POST /api/calls/incoming  (Twilio webhook)
    │   ├── catalog.py                    # POST /api/catalog/from-text|from-audio
    │   └── upload.py                     # POST /api/upload/call-image (image during call) and outbound.js route
          
    ├── realtime/
    │   ├── call_sessions.py              # Per-call state — in-memory (dev) or Redis (prod)
    │   └── call_socket.py                # WSS /ws/call-stream — live audio pipeline
    └── services/
        ├── telephony/
        │   ├── base.py                   # Abstract interface — swap provider in .env
        │   ├── twilio.py                 # Twilio implementation
        │   └── exotel.py                 # Exotel skeleton (Indian alternative)
        ├── stt/
        │   └── base.py                   # Deepgram streaming STT + file transcription
        ├── tts/
        │   └── base.py                   # Cartesia / Sarvam / ElevenLabs TTS
        ├── ai/
        │   ├── catalog_extractor.py      # One-shot: transcript + image → catalog JSON
        │   └── conversation_agent.py     # Multi-turn: stateful call conversation  and base.py 
        └── storage/
            └── base.py                   # Local / S3 / GCS — for images uploaded during calls
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — minimum keys needed to run:

| Key                                        | Get from                                             | Free?           |
| ------------------------------------------ | ---------------------------------------------------- | --------------- |
| `GEMINI_API_KEY`                           | [aistudio.google.com](https://aistudio.google.com)   | ✅ Free         |
| `DEEPGRAM_API_KEY`                         | [console.deepgram.com](https://console.deepgram.com) | ✅ $200 credit  |
| `CARTESIA_API_KEY` + `CARTESIA_VOICE_ID`   | [play.cartesia.ai](https://play.cartesia.ai)         | ✅ Free trial   |
| `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` | [console.twilio.com](https://console.twilio.com)     | ⚠️ ~₹8/min      |
| `TWILIO_PHONE_NUMBER`                      | Twilio Console → Buy Number                          | ⚠️ ~$1.15/month |
| `MONGODB_URL`                              | Local or [MongoDB Atlas](https://cloud.mongodb.com)  | ✅ Free tier    |

### 3. Start the server

```bash
uvicorn main:app --reload --port 8000
```

On startup the console prints which providers are active:

```
[app] Telephony : twilio
[app] STT       : deepgram
[app] TTS       : cartesia
[app] AI        : gemini
[app] Storage   : local
[mongo] Connected to seller_catalog
```

### 4. Expose with ngrok (local dev)

```bash
ngrok http 8000
```

Copy the URLs into `.env`:

```env
PUBLIC_BASE_URL=https://abc123.ngrok.io
PUBLIC_WS_URL=wss://abc123.ngrok.io/ws/call-stream
```

### 5. Configure Twilio

In [Twilio Console](https://console.twilio.com) → Phone Numbers → your number:

| Setting             | Value                                                    |
| ------------------- | -------------------------------------------------------- |
| A call comes in     | `https://abc123.ngrok.io/api/calls/incoming` (HTTP POST) |
| Call status changes | `https://abc123.ngrok.io/api/calls/status` (HTTP POST)   |

### 6. Make a test call

Call your Twilio number. You'll hear the greeting in the configured default language and can describe a product. The completed catalog is saved to MongoDB under the `catalogs` collection.

---

## Swapping Providers

Change **one line in `.env`** — nothing else in the codebase changes.

| What           | `.env` key           | Options                                   |
| -------------- | -------------------- | ----------------------------------------- |
| Phone provider | `TELEPHONY_PROVIDER` | `twilio` · `exotel` · `plivo`             |
| Speech-to-text | `STT_PROVIDER`       | `deepgram`                                |
| Text-to-speech | `TTS_PROVIDER`       | `cartesia` · `sarvam` · `elevenlabs`      |
| AI model       | `AI_PROVIDER`        | `gemini` · `openai`                       |
| File storage   | `STORAGE_PROVIDER`   | `local` · `s3` · `gcs`                    |
| Session store  | `REDIS_URL`          | blank = in-memory · `redis://...` = Redis |

---

## Language Support

Language is **auto-detected from the seller's speech** by Deepgram — no manual setting needed per call. The AI then responds in the same language.

| Language     | Code | STT             | TTS                                     |
| ------------ | ---- | --------------- | --------------------------------------- |
| Hindi        | `hi` | Deepgram Nova-2 | Cartesia `sonic-multilingual` or Sarvam |
| Telugu       | `te` | Deepgram Nova-2 | Sarvam `bulbul:v1` (recommended)        |
| Tamil        | `ta` | Deepgram Nova-2 | Sarvam `bulbul:v1`                      |
| Marathi      | `mr` | Deepgram Nova-2 | Sarvam `bulbul:v1`                      |
| Kannada      | `kn` | Deepgram Nova-2 | Sarvam `bulbul:v1`                      |
| English (IN) | `en` | Deepgram Nova-2 | Cartesia                                |

To add a new language, edit only `app/core/languages.py` — add one `LanguageConfig` entry with its greeting, TTS voice, and STT code.

---

## Image Upload During a Call

While a call is active, the seller can upload a product photo from your companion app or WhatsApp bot:

```
POST /api/upload/call-image?call_sid=CA...
Content-Type: multipart/form-data
Body: image (jpg/png/webp, max 10MB)
```

The image is analyzed by Gemini Vision immediately and linked to the live call. On the next AI turn, product attributes (color, pattern, material) are filled in automatically from the photo.

---

## MongoDB Collections

Two collections are written after every call:

**`catalogs`** — one document per completed product:

```json
{
  "call_sid":     "CA...",
  "seller_phone": "+91...",
  "language":     "hi",
  "created_at":   1234567890,
  "intent":       "CREATE_PRODUCT",
  "confidence":   87,
  "product":      { "title": "...", "category": "...", "pricing": {}, ... },
  "collected":    { "color": "black", "price": 499, "quantity": 50, ... },
  "transcripts":  [ { "text": "...", "confidence": 0.97 } ],
  "image_url":    "https://..."
}
```

**`calls`** — one document per call (including incomplete ones):

```json
{
  "call_sid":    "CA...",
  "caller":      "+91...",
  "language":    "hi",
  "started_at":  1234567890,
  "ended_at":    1234567950,
  "turn_count":  6,
  "is_complete": true,
  "history":     [ { "role": "user", "content": "..." }, ... ],
  "transcripts": [ ... ]
}
```

---

## HTTP API Reference

| Method | Path                           | Description                                |
| ------ | ------------------------------ | ------------------------------------------ |
| `GET`  | `/health`                      | Server status + active providers           |
| `POST` | `/api/calls/incoming`          | Twilio webhook — incoming call entry point |
| `POST` | `/api/calls/status`            | Twilio call lifecycle callback             |
| `POST` | `/api/catalog/from-text`       | Transcript → catalog JSON (any language)   |
| `POST` | `/api/catalog/from-audio`      | Audio file → catalog JSON                  |
| `POST` | `/api/catalog/analyze-image`   | Product image → visual attributes          |
| `POST` | `/api/catalog/transcribe`      | Audio file → transcript only               |
| `POST` | `/api/upload/call-image`       | Upload product image during active call    |
| `POST` | `/api/upload/standalone-image` | Analyze image without a call               |
| `WS`   | `/ws/call-stream`              | Twilio Media Stream WebSocket              |

Interactive docs: `http://localhost:8000/docs`

---

## Production Checklist

- [ ] Set `APP_ENV=production` in `.env`
- [ ] Set `REDIS_URL` — sessions survive restarts and scale horizontally
- [ ] Set `MONGODB_URL` to Atlas connection string
- [ ] Set `STORAGE_PROVIDER=s3` or `gcs` — local disk won't persist on cloud servers
- [ ] Set `TWILIO_AUTH_TOKEN` — enables request signature validation
- [ ] Deploy behind HTTPS (Twilio requires it) — use Nginx + Let's Encrypt or a cloud platform
- [ ] Remove `ngrok` URLs from `.env`, set real `PUBLIC_BASE_URL` and `PUBLIC_WS_URL`





Seller speaks
↓
Deepgram STT
↓
process_turn()
↓
Rule-based extraction
↓
Collected state updated
↓
Build lightweight prompt
↓
LLM fallback
↓
JSON response
↓
TTS
↓
Twilio websocket audio


<!-- full flow -->

Caller speaks
    ↓
Twilio Media Stream
    ↓
WebSocket receives audio
    ↓
Deepgram STT
    ↓
on_transcript()
    ↓
process_turn()
    ↓
LLM
    ↓
response_text
    ↓
TTS synthesize
    ↓
_send_audio()
    ↓
Twilio playback
    ↓
Caller hears response



Ollama      → LLM (replaces Groq/Gemini)
Whisper     → STT (replaces Deepgram)
edge-tts    → TTS (replaces Cartesia/Sarvam)

pip install faster-whisper
pip install edge-tts



# 1. Download and install
winget install Ollama.Ollama

# 2. Pull the model (8b = ~5GB, needs 8GB RAM)
ollama pull llama3.1:8b

# 3. Pull vision model for image analysis
ollama pull llava:7b

# 4. Start server (runs on port 11434)
ollama serve

curl.exe http://localhost:11434/api/tags


CPU only:  Groq + Deepgram + Cartesia  (cloud, fast, cheap)
With GPU:  Ollama + Whisper + edge-tts (self-hosted, private, free)