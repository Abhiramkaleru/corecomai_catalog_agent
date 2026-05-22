"""
app/services/stt/base.py + Deepgram implementation
──────────────────────────────────────────────────────────────────────────────
STT provider abstraction. Change STT_PROVIDER in .env to swap.
"""

import asyncio
import json
import base64
from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional

from app.core.config import settings

TranscriptCallback = Callable[[str, str, bool, float, list], Awaitable[None]]
# call_sid, text, is_final, confidence, languages


class STTSession(ABC):
    @abstractmethod
    async def connect(self) -> None: ...
    @abstractmethod
    async def send_audio(self, audio_bytes: bytes) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...


# ── Deepgram ──────────────────────────────────────────────────────────────

class DeepgramSession(STTSession):
    """
    Streams mulaw 8kHz audio to Deepgram and fires on_transcript callbacks.
    Uses language=multi for multilingual Indian callers (hi, te, ta, kn, mr, en).
    NOTE: detect_language=true does NOT work with encoding=mulaw — use language=multi instead.
    """

    DG_URL = (
        "wss://api.deepgram.com/v1/listen"
        "?model=nova-2"
        "&language=multi"           # multilingual — works with mulaw
        "&punctuate=true"
        "&interim_results=true"
        # "&encoding=linear16"           # Exotel sends mulaw
        "&encoding=mulaw"                   #Twilio sends mulaw
        "&sample_rate=8000"         # Exotel streams at 8kHz
        "&channels=1"
        "&endpointing=500"          # 300ms silence = end of utterance
        "&utterance_end_ms=1500"
    )



    def __init__(self, call_sid: str, on_transcript: TranscriptCallback):
        self.call_sid      = call_sid
        self.on_transcript = on_transcript
        self._ws           = None
        self._recv_task    = None

    async def connect(self) -> None:
        import websockets

        headers = {"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"}
        print(f"[deepgram] Connecting to: {self.DG_URL}")
        print(f"[deepgram] Headers: {headers}")

        # websockets >= 12 uses additional_headers instead of extra_headers
        self._ws = await websockets.connect(self.DG_URL, additional_headers=headers)
        print(f"[deepgram] Connected — {self.call_sid}")

        self._recv_task = asyncio.create_task(self._receive_loop())

    async def send_audio(self, audio_bytes: bytes) -> None:
        if self._ws:
            try:
                await self._ws.send(audio_bytes)
            except Exception as e:
                print(f"[deepgram] send_audio error [{self.call_sid}]: {e}")

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        print(f"[deepgram] Closed — {self.call_sid}")

    async def _receive_loop(self) -> None:
        try:
            async for message in self._ws:
                await self._handle_message(message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[deepgram] receive_loop error [{self.call_sid}]: {e}")

    async def _handle_message(self, message: str) -> None:
        try:
            data       = json.loads(message)
            msg_type   = data.get("type", "")

            if msg_type == "Results":
                channel    = data.get("channel", {})
                alts       = channel.get("alternatives", [{}])
                transcript = alts[0].get("transcript", "").strip()
                confidence = alts[0].get("confidence", 0.0)
                is_final   = data.get("is_final", False)

                # Detected languages (Deepgram returns list of dicts)
                raw_langs  = data.get("channel", {}).get("detected_language", "")
                languages  = [raw_langs] if raw_langs else []

                if transcript:
                    await self.on_transcript(
                        self.call_sid,
                        transcript,
                        is_final,
                        confidence,
                        languages,
                    )

            elif msg_type == "Metadata":
                print(f"[deepgram] Metadata [{self.call_sid}]: {data}")

            elif msg_type == "Error":
                print(f"[deepgram] Error [{self.call_sid}]: {data}")

        except Exception as e:
            print(f"[deepgram] _handle_message error [{self.call_sid}]: {e}")


class WhisperSession(STTSession):
    """
    Self-hosted Whisper STT via faster-whisper.
    Runs locally — no API key needed.
    Supports all Indian languages automatically.
    """

    def __init__(self, call_sid: str, on_transcript: TranscriptCallback):
        self.call_sid      = call_sid
        self.on_transcript = on_transcript
        self._audio_buffer = bytearray()
        self._task         = None
        self._running      = False

    async def connect(self) -> None:
        from faster_whisper import WhisperModel
        model_size = getattr(settings, "WHISPER_MODEL", "small")
        # Load model once — cache at module level
        self._model  = _get_whisper_model(model_size)
        self._running = True
        self._task    = asyncio.create_task(self._process_loop())
        print(f"[whisper] Connected — {self.call_sid}")

    async def send_audio(self, audio_bytes: bytes) -> None:
        # Convert mulaw → PCM16 before buffering
        import audioop
        pcm = audioop.ulaw2lin(audio_bytes, 2)
        self._audio_buffer.extend(pcm)

    async def close(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print(f"[whisper] Closed — {self.call_sid}")

    async def _process_loop(self) -> None:
        """Process audio buffer every 2 seconds."""
        import io
        import wave

        while self._running:
            await asyncio.sleep(2.0)  # process every 2 seconds

            if len(self._audio_buffer) < 16000:  # min 1 second of audio
                continue

            # Take current buffer
            pcm_data = bytes(self._audio_buffer)
            self._audio_buffer.clear()

            # Run Whisper in thread pool (CPU intensive)
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, self._transcribe, pcm_data
            )

            if text and text.strip():
                await self.on_transcript(
                    self.call_sid,
                    text.strip(),
                    True,   # always final
                    0.9,
                    [],
                )

    def _transcribe(self, pcm_data: bytes) -> str:
        import numpy as np

        audio_np = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0

        segments, info = self._model.transcribe(
            audio_np,
            beam_size=3,
            language="en",              # fix language — stops Japanese hallucination
            condition_on_previous_text=False,
            vad_filter=True,            # filter silence
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 200,
            },
            no_speech_threshold=0.6,    # ignore if confidence < 60%
            log_prob_threshold=-1.0,    # reject low probability segments
            compression_ratio_threshold=2.4,
        )

        results = list(segments)
        
        # Filter out hallucinations
        text = " ".join(
            s.text for s in results
            if s.no_speech_prob < 0.5    # skip if likely silence
            and s.avg_logprob > -1.0     # skip low confidence
        ).strip()

        return text
# ── Whisper model cache ───────────────────────────────────────────────────────
_whisper_model = None

def _get_whisper_model(size: str = "small"):
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print(f"[whisper] Loading model: {size}")
        _whisper_model = WhisperModel(
            size,
            device          = "cpu",   # change to "cuda" if GPU available
            compute_type    = "int8",  # fastest on CPU
        )
        print(f"[whisper] Model loaded")
    return _whisper_model
# ── Factory ───────────────────────────────────────────────────────────────

def get_stt_session(call_sid: str, on_transcript: TranscriptCallback) -> STTSession:
    p = settings.STT_PROVIDER.lower()
    if p == "deepgram":
        return DeepgramSession(call_sid, on_transcript)
    elif p == "whisper":
        return WhisperSession(call_sid, on_transcript)
    else:
        raise ValueError(f"Unknown STT_PROVIDER='{p}'. Supported: deepgram")
    

    
# ── File transcription (for catalog.py upload endpoints) ─────────────────

async def transcribe_file(audio_bytes: bytes, language: str = "en") -> str:
    """
    One-shot transcription of an audio file using Deepgram REST API.
    Used by /api/catalog upload endpoints (not live call streaming).
    """
    import httpx

    lang_map = {
        "en": "en-IN", "hi": "hi", "te": "te",
        "ta": "ta",    "mr": "mr", "kn": "kn",
    }
    dg_lang = lang_map.get(language, "en-IN")

    url = (
        f"https://api.deepgram.com/v1/listen"
        f"?model=nova-2&language={dg_lang}&punctuate=true"
    )
    headers = {
        "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
        "Content-Type":  "audio/wav",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, content=audio_bytes, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    try:
        return data["results"]["channels"][0]["alternatives"][0]["transcript"]
    except (KeyError, IndexError):
        return ""