"""Tiny async client for Ollama's /api/chat.

The model runs CPU-only at the lowest priority on a shared box, so requests are
non-streaming, short, and never set keep_alive (the server decides that).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiohttp

TIMEOUT_SECONDS = 240  # a cold model can take minutes to load
REPLY_TOKENS = 150
CLASSIFY_TOKENS = 4
# gpt-oss spends part of num_predict on its reasoning, even at think=low
THINK_BUDGET = 350


class LLMTimeout(Exception):
    pass


class LLMError(Exception):
    pass


@dataclass
class Reply:
    text: str
    truncated: bool


def wants_low_think(model: str) -> bool:
    """gpt-oss style reasoning models get think=low; others must not get it."""
    name = model.lower()
    return "chat" in name or "gpt-oss" in name


def build_payload(model: str, messages: list[dict], num_predict: int, temperature: float) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": num_predict, "temperature": temperature},
    }
    if wants_low_think(model):
        payload["think"] = "low"
        payload["options"]["num_predict"] = num_predict + THINK_BUDGET
    return payload


def model_tag(model: str) -> str:
    return model if ":" in model else model + ":latest"


class Ollama:
    def __init__(self, base_url: str, model: str, session: aiohttp.ClientSession):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.session = session

    async def chat(
        self, messages: list[dict], num_predict: int = REPLY_TOKENS, temperature: float = 0.9
    ) -> Reply:
        payload = build_payload(self.model, messages, num_predict, temperature)
        try:
            async with self.session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS),
            ) as resp:
                if resp.status != 200:
                    raise LLMError(f"HTTP {resp.status}")
                data = await resp.json()
        except asyncio.TimeoutError as exc:
            raise LLMTimeout() from exc
        except aiohttp.ClientError as exc:
            raise LLMError(type(exc).__name__) from exc
        message = data.get("message") or {}
        return Reply(
            text=message.get("content") or "",
            truncated=data.get("done_reason") == "length",
        )

    async def classify(self, messages: list[dict]) -> str:
        reply = await self.chat(messages, num_predict=CLASSIFY_TOKENS, temperature=0.0)
        return reply.text

    async def model_loaded(self) -> bool:
        """True if our model is already in memory, so a chime never forces a reload."""
        async with self.session.get(
            f"{self.base_url}/api/ps", timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                return False
            data = await resp.json()
        wanted = model_tag(self.model)
        return any(
            model_tag(m.get("name") or m.get("model") or "") == wanted
            for m in data.get("models") or []
        )
