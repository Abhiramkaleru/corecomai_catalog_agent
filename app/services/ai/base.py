"""
app/services/ai/base.py
──────────────────────────────────────────────────────────────────────────────
AI provider abstraction. Change AI_PROVIDER in .env to swap vendors.

Supported providers:
  gemini  → Google Gemini (gemini-2.0-flash)
  openai  → OpenAI (gpt-4o)

All providers expose the same two methods:
  generate(system, user_message)            → str
  generate_with_image(system, image, text)  → str   (image = bytes | url str)
"""

from __future__ import annotations

import asyncio
import base64
from abc import ABC, abstractmethod
from typing import Union

from app.core.config import settings
import time

# ── Abstract base ──────────────────────────────────────────────────────────

class AIProvider(ABC):

    @abstractmethod
    async def generate(
        self,
        system: str,
        user_message: str,
    ) -> str:
        """
        Single-turn text generation.
        Returns the raw text response from the model.
        """
        ...

    @abstractmethod
    async def generate_with_image(
        self,
        system: str,
        image: Union[bytes, str],          # bytes → raw image; str → public URL
        media_type: str,                   # e.g. "image/jpeg"
        text_prompt: str,
    ) -> str:
        """
        Vision call: analyze an image alongside a text prompt.
        Returns the raw text response from the model.
        """
        ...


# ── Gemini ─────────────────────────────────────────────────────────────────

class GeminiAIProvider(AIProvider):
    """Google Gemini via the google-genai SDK."""

    def __init__(self) -> None:
        from google import genai
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._model  = "gemini-2.0-flash"

    # async def generate(self, system: str, user_message: str) -> str:
    #     from google.genai import types

    #     response = self._client.models.generate_content(
    #         model=self._model,
    #         config=types.GenerateContentConfig(system_instruction=system),
    #         contents=user_message,
    #     )
    #     return response.text

    async def generate(self, system: str, user_message: str) -> str:
        from google.genai import types
        response = self._client.models.generate_content(
            model=self._model,
            config=types.GenerateContentConfig(system_instruction=system),
            contents=user_message,
        )
        # Track tokens
        usage = response.usage_metadata
        _log_tokens(self._model, usage.prompt_token_count, usage.candidates_token_count, "generate")
        return response.text

    async def generate_with_image(
        self,
        system: str,
        image: Union[bytes, str],
        media_type: str,
        text_prompt: str,
    ) -> str:
        from google.genai import types

        if isinstance(image, bytes):
            image_part = types.Part.from_bytes(data=image, mime_type=media_type)
        else:
            # Public URL
            image_part = types.Part.from_uri(file_uri=image, mime_type=media_type)

        response = self._client.models.generate_content(
            model=self._model,
            config=types.GenerateContentConfig(system_instruction=system),
            contents=[image_part, text_prompt],
        )
        return response.text


# ── OpenAI ─────────────────────────────────────────────────────────────────

class OpenAIAIProvider(AIProvider):
    """OpenAI via the openai SDK."""

    def __init__(self) -> None:
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model  = "gpt-4o"

    # async def generate(self, system: str, user_message: str) -> str:
    #     resp = await self._client.chat.completions.create(
    #         model=self._model,
    #         messages=[
    #             {"role": "system",  "content": system},
    #             {"role": "user",    "content": user_message},
    #         ],
    #     )
    #     return resp.choices[0].message.content or ""
    async def generate(self, system: str, user_message: str) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_message},
            ],
        )
        # Track tokens
        usage = resp.usage
        _log_tokens(self._model, usage.prompt_tokens, usage.completion_tokens, "generate")
        return resp.choices[0].message.content or ""
    async def generate_with_image(
        self,
        system: str,
        image: Union[bytes, str],
        media_type: str,
        text_prompt: str,
    ) -> str:
        # Build image content block
        if isinstance(image, bytes):
            b64 = base64.b64encode(image).decode()
            image_block = {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{b64}"},
            }
        else:
            # Public URL
            image_block = {
                "type": "image_url",
                "image_url": {"url": image},
            }

        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        image_block,
                        {"type": "text", "text": text_prompt},
                    ],
                },
            ],
        )
        return resp.choices[0].message.content or ""



# ── Groq (Llama) ───────────────────────────────────────────────────────────

class GroqAIProvider(AIProvider):
    """Groq inference — llama-3.3-70b-versatile (fast & free tier available)."""

    def __init__(self) -> None:
        from groq import AsyncGroq
        self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self._model  = "llama-3.3-70b-versatile"
        # self._model  = "llama-3.1-8b-instant"

    # async def generate(self, system: str, user_message: str) -> str:
    #     resp = await self._client.chat.completions.create(
    #         model=self._model,
    #         messages=[
    #             {"role": "system", "content": system},
    #             {"role": "user",   "content": user_message},
    #         ],
    #     )
    #     return resp.choices[0].message.content or ""

    async def generate(self, system: str, user_message: str) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=300,
            temperature=0.1,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_message},
            ],
        )
        # Track tokens
        usage = resp.usage
        _log_tokens(self._model, usage.prompt_tokens, usage.completion_tokens, "generate")
        return resp.choices[0].message.content or ""

# In base.py — two separate model configs

# class GroqAIProvider(AIProvider):
    
#     def __init__(self) -> None:
#         from groq import AsyncGroq
#         self._client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        
#         # 70b for conversation — needs reliable JSON every turn
#         self._conv_model    = "llama-3.3-70b-versatile"
        
#         # 8b for catalog extraction — simpler task, one-shot
#         # self._extract_model = "llama-3.1-8b-instant"

#     async def generate(self, system: str, user_message: str) -> str:
#         # Use 70b for conversation (short system prompt detection)
#         # Use 8b for catalog extraction (longer system prompt)
#         is_conversation = len(system) < 1500
#         model = self._conv_model if is_conversation else self._extract_model
        
#         max_tokens  = 300  if is_conversation else 600
#         temperature = 0.1  if is_conversation else 0.2

#         resp = await self._client.chat.completions.create(
#             model=model,
#             max_tokens=max_tokens,
#             temperature=temperature,
#             messages=[
#                 {"role": "system", "content": system},
#                 {"role": "user",   "content": user_message},
#             ],
#         )
#         usage = resp.usage
#         _log_tokens(model, usage.prompt_tokens, usage.completion_tokens, "generate")
#         return resp.choices[0].message.content or ""
    async def generate_with_image(
        self,
        system: str,
        image: Union[bytes, str],
        media_type: str,
        text_prompt: str,
    ) -> str:
        # llama-3.3-70b-versatile is text-only — fall back to text description
        print("[groq] WARNING: generate_with_image called but Groq/Llama is text-only — using text prompt only")
        return await self.generate(system, text_prompt)
# # ── Factory ────────────────────────────────────────────────────────────────

class OllamaAIProvider(AIProvider):
    """
    Self-hosted LLM via Ollama.
    Install: https://ollama.ai
    Run: ollama serve && ollama pull llama3.1
    """

    def __init__(self) -> None:
        self.url   = getattr(settings, "OLLAMA_URL", "http://localhost:11434")
        self._model = getattr(settings, "OLLAMA_MODEL", "llama3.1:8b")

    async def generate(self, system: str, user_message: str) -> str:
        import httpx

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
                ) as client:
                    resp = await client.post(
                        f"{self.url}/api/chat",
                        json={
                            "model":  self._model,
                            "stream": False,
                            "options": {"temperature": 0.1, "num_predict": 300},
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user",   "content": user_message},
                            ],
                        },
                    )
                    resp.raise_for_status()
                    _log_tokens(self._model, 0, 0, "generate") 
                    return resp.json()["message"]["content"] or ""

            except httpx.ReadTimeout:
                print(f"[ollama] Timeout attempt {attempt+1}/3")
                if attempt == 2:
                    raise
                await asyncio.sleep(1)
    async def generate_with_image(
        self,
        system: str,
        image: bytes | str,
        media_type: str,
        text_prompt: str,
    ) -> str:
        import base64
        import httpx

        # Use llava for vision if available
        image_b64 = (
            base64.b64encode(image).decode()
            if isinstance(image, bytes)
            else image
        )

        payload = {
            "model":  getattr(settings, "OLLAMA_VISION_MODEL", "llava:7b"),
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": text_prompt,
                    "images": [image_b64],
                },
            ],
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return data["message"]["content"] or ""


class VLLMAIProvider(AIProvider):
    """
    Self-hosted LLM via vLLM (OpenAI-compatible API).
    Run: python -m vllm.entrypoints.openai.api_server --model meta-llama/Llama-3.1-8B
    """

    def __init__(self) -> None:
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            api_key  = "not-needed",
            base_url = getattr(settings, "VLLM_URL", "http://localhost:8000/v1"),
        )
        self._model = getattr(settings, "VLLM_MODEL", "meta-llama/Llama-3.1-8B")

    async def generate(self, system: str, user_message: str) -> str:
        resp = await self._client.chat.completions.create(
            model       = self._model,
            max_tokens  = 300,
            temperature = 0.1,
            messages    = [
                {"role": "system", "content": system},
                {"role": "user",   "content": user_message},
            ],
        )
        return resp.choices[0].message.content or ""

    async def generate_with_image(self, system, image, media_type, text_prompt):
        # vLLM vision depends on model — fallback to text only
        return await self.generate(system, text_prompt)

def get_ai_provider() -> AIProvider:
    p = settings.AI_PROVIDER.lower()
    if p == "gemini":
        return GeminiAIProvider()
    elif p == "openai":
        return OpenAIAIProvider()
    elif p == "groq":
        return GroqAIProvider()
    elif p == "ollama": return OllamaAIProvider()   # add this
    elif p == "vllm":   return VLLMAIProvider()  
    else:
        raise ValueError(
            f"Unknown AI_PROVIDER='{p}'. Supported: gemini, openai"
        )


# Singleton — import `ai` wherever you need the active provider
ai: AIProvider = get_ai_provider()




_token_log: list[dict] = []

def get_token_stats() -> dict:
    if not _token_log:
        return {"calls": 0, "total_input": 0, "total_output": 0, "total_tokens": 0, "cost_usd": 0}
    
    total_input  = sum(r["input_tokens"]  for r in _token_log)
    total_output = sum(r["output_tokens"] for r in _token_log)
    
    # Approximate costs (per 1M tokens)
    costs = {
        "gemini-2.0-flash":         {"input": 0.10,  "output": 0.40},
        "gpt-4o":                   {"input": 2.50,  "output": 10.0},
        "llama-3.3-70b-versatile":  {"input": 0.059, "output": 0.079},
         "llama-3.1-8b-instant":    {"input": 0.020, "output": 0.016},
    }
    
    cost = 0.0
    for r in _token_log:
        c = costs.get(r["model"], {"input": 0, "output": 0})
        cost += (r["input_tokens"] / 1_000_000) * c["input"]
        cost += (r["output_tokens"] / 1_000_000) * c["output"]
    
    return {
        "calls":        len(_token_log),
        "total_input":  total_input,
        "total_output": total_output,
        "total_tokens": total_input + total_output,
        "cost_usd":     round(cost, 6),
        "log":          _token_log[-10:],  # last 10 calls
    }

def _log_tokens(model: str, input_tokens: int, output_tokens: int, call_type: str):
    _token_log.append({
        "model":         model,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "call_type":     call_type,
        "timestamp":     time.time(),
    })
    print(f"[tokens] {call_type} — in={input_tokens} out={output_tokens} model={model}")