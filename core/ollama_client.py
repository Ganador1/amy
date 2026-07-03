"""
Ollama Cloud Client — Dual API key load balancer for A.M.Y.

Connects to Ollama Cloud (https://ollama.com/api) using two API keys
in round-robin with automatic failover. If one key is rate-limited or
fails, the other takes over seamlessly.

Implements the /api/chat endpoint (OpenAI-compatible messages format).
"""
import asyncio
import json
import os
import time
from itertools import cycle

import httpx
import structlog

log = structlog.get_logger()

# Load API keys from environment / .env
_env_loaded = False


def _load_env():
    """Load .env file if it exists. Idempotent — safe to call multiple times."""
    global _env_loaded
    if _env_loaded:
        return
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())
    _env_loaded = True


def get_ollama_cloud_api_keys() -> list[str]:
    """Return Ollama Cloud keys in documented priority order.

    ``OLLAMA_CLOUD_API_KEY`` is the primary key documented in README/.env.
    ``OLLAMA_CLOUD_API_KEY_1`` is retained only as a legacy alias when the
    primary key is absent, and ``OLLAMA_CLOUD_API_KEY_2`` is the documented
    failover key. Duplicates are removed while preserving order.
    """
    _load_env()
    primary = os.environ.get("OLLAMA_CLOUD_API_KEY", "")
    legacy_primary = os.environ.get("OLLAMA_CLOUD_API_KEY_1", "")
    ordered = [
        primary or legacy_primary,
        os.environ.get("OLLAMA_CLOUD_API_KEY_2", ""),
    ]
    keys: list[str] = []
    seen: set[str] = set()
    for key in ordered:
        key = key.strip()
        if key and key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def get_primary_ollama_cloud_api_key() -> str:
    """Return the first configured Ollama Cloud key, or an empty string."""
    keys = get_ollama_cloud_api_keys()
    return keys[0] if keys else ""


class OllamaCloudClient:
    """
    Async client for Ollama Cloud API with dual-key round-robin.

    Usage:
        client = OllamaCloudClient(config)
        response = await client.chat(model="glm5.1", messages=[...])
    """

    def __init__(self, config: dict):
        _load_env()  # Lazy: only loads .env the first time
        self.base_url = config.get("base_url", "https://ollama.com/api")
        self.config = config

        # Load API keys (primary + legacy alias + optional failover).
        self._keys = get_ollama_cloud_api_keys()
        if not self._keys:
            raise ValueError(
                "No Ollama Cloud API keys found. "
                "Set OLLAMA_CLOUD_API_KEY and/or OLLAMA_CLOUD_API_KEY_2 in .env"
            )

        self._key_cycle = cycle(range(len(self._keys)))
        self._key_failures: dict[int, float] = {}  # key_index → last_failure_time
        self._cooldown_seconds = 120  # Wait 2 min before retrying a rate-limited key

        # Shared httpx async client (connection pooling)
        self._http: httpx.AsyncClient | None = None

        log.info(
            "ollama_cloud.initialized",
            base_url=self.base_url,
            keys_loaded=len(self._keys),
        )

    def _read_timeout(self) -> float:
        # Per-byte read timeout. Ollama Cloud latency for newer models is very
        # spiky (2s one call, >120s the next when queued). Override with
        # config["read_timeout"] or env OLLAMA_READ_TIMEOUT.
        return float(
            self.config.get("read_timeout")
            or os.environ.get("OLLAMA_READ_TIMEOUT", "120")
        )

    def _total_timeout(self) -> float:
        # Hard WALL-CLOCK cap on a single request. httpx's read timeout only
        # fires between bytes, so a model that *streams* its 'thinking' slowly
        # (e.g. minimax-m3) never trips it and can run for many minutes. This
        # total cap guarantees a single chat() call cannot hang a cognitive
        # cycle. Override with config["total_timeout"] / OLLAMA_TOTAL_TIMEOUT.
        return float(
            self.config.get("total_timeout")
            or os.environ.get("OLLAMA_TOTAL_TIMEOUT", "90")
        )

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._read_timeout(), connect=10.0)
            )
        return self._http

    def _pick_key(self) -> tuple[int, str]:
        """Pick the next available API key (round-robin with cooldown)."""
        now = time.time()
        for _ in range(len(self._keys)):
            idx = next(self._key_cycle)
            last_fail = self._key_failures.get(idx, 0)
            if now - last_fail > self._cooldown_seconds:
                return idx, self._keys[idx]

        # All keys in cooldown — use the least recently failed one
        idx = min(self._key_failures, key=self._key_failures.get, default=0)
        return idx, self._keys[idx]

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        format_json: bool = False,
        num_ctx: int | None = None,
        think: bool | None = None,
    ) -> dict:
        """
        Send a chat completion request to Ollama Cloud.

        ``think=False`` disables the reasoning trace on thinking models
        (glm-5.1 etc.). This matters for structured-output calls: a thinking
        model can burn the entire ``num_predict`` budget on its hidden trace
        and return an EMPTY ``content`` (we observed eval_count == max_tokens
        with 9k chars of thinking and 7 chars of content), which downstream
        JSON parsing reads as a failure.

        Returns the full response dict with 'message' containing the assistant reply.
        """
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if num_ctx:
            payload["options"]["num_ctx"] = num_ctx
        if format_json:
            payload["format"] = "json"
        if think is not None:
            payload["think"] = think

        # Try with failover
        last_error = None
        for attempt in range(len(self._keys)):
            key_idx, api_key = self._pick_key()
            try:
                result = await self._do_request(
                    endpoint="/chat",
                    payload=payload,
                    api_key=api_key,
                )
                # Clear failure record on success
                self._key_failures.pop(key_idx, None)
                return result
            except Exception as e:
                last_error = e
                self._record_failure(key_idx, e)
                err_msg = type(e).__name__ + (f': {e}' if str(e) else '')
                log.warning(
                    "ollama_cloud.key_failed",
                    key_index=key_idx,
                    error=err_msg,
                    attempt=attempt + 1,
                    retry_after=getattr(e, "retry_after", None),
                )
                # Pequeña pausa antes de intentar la siguiente key
                if attempt < len(self._keys) - 1:
                    await asyncio.sleep(3)

        raise RuntimeError(f"All Ollama Cloud keys failed. Last error: {type(last_error).__name__}: {last_error}")

    async def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        format_json: bool = False,
    ) -> dict:
        """Simple generate (non-chat) endpoint."""
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if format_json:
            payload["format"] = "json"

        last_error = None
        for attempt in range(len(self._keys)):
            key_idx, api_key = self._pick_key()
            try:
                result = await self._do_request("/generate", payload, api_key)
                self._key_failures.pop(key_idx, None)
                return result
            except Exception as e:
                last_error = e
                self._record_failure(key_idx, e)

        raise RuntimeError(f"All keys failed. Last error: {last_error}")

    async def embed(self, model: str, input_text: str | list[str]) -> list[list[float]]:
        """Generate embeddings (with the same key failover as chat/generate)."""
        payload = {
            "model": model,
            "input": input_text,
        }
        last_error = None
        for attempt in range(len(self._keys)):
            key_idx, api_key = self._pick_key()
            try:
                result = await self._do_request("/embed", payload, api_key)
                self._key_failures.pop(key_idx, None)
                return result.get("embeddings", [])
            except Exception as e:
                last_error = e
                self._record_failure(key_idx, e)
                if attempt < len(self._keys) - 1:
                    await asyncio.sleep(1)
        raise RuntimeError(f"All keys failed for embed. Last error: {last_error}")

    async def _do_request(self, endpoint: str, payload: dict, api_key: str) -> dict:
        """Execute a single HTTP request to Ollama Cloud.

        Wrapped in a hard wall-clock timeout so a slowly-streaming model can
        never hang a cognitive cycle (httpx's read timeout only fires between
        bytes and is defeated by continuous 'thinking' token streams).
        """
        http = await self._get_http()
        url = f"{self.base_url}{endpoint}"

        response = await asyncio.wait_for(
            http.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            ),
            timeout=self._total_timeout(),
        )

        if response.status_code != 200:
            body = response.text[:500]
            err = httpx.HTTPStatusError(
                f"Ollama Cloud returned {response.status_code}: {body}",
                request=response.request,
                response=response,
            )
            # Surface a server-provided Retry-After (seconds) on 429/503 so the
            # failover loop can honor it instead of the fixed 120s cooldown.
            if response.status_code in (429, 503):
                err.retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
            raise err

        return response.json()

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        """Parse a Retry-After header (delta-seconds form). Returns None if
        absent/unparseable (HTTP-date form is uncommon here and ignored)."""
        if not value:
            return None
        try:
            return max(0.0, float(value.strip()))
        except (ValueError, AttributeError):
            return None

    def _record_failure(self, key_idx: int, exc: Exception) -> None:
        """Mark a key failed, extending the cooldown to honor a 429 Retry-After."""
        retry_after = getattr(exc, "retry_after", None)
        if retry_after:
            # Encode the desired ready-time within the fixed-cooldown scheme:
            # _pick_key compares (now - last_fail) > cooldown, so set last_fail
            # so the key becomes available exactly retry_after seconds from now.
            self._key_failures[key_idx] = time.time() + retry_after - self._cooldown_seconds
        else:
            self._key_failures[key_idx] = time.time()

    async def close(self):
        """Close the HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def health_check(self) -> dict:
        """Check if both API keys work."""
        results = {}
        for i, key in enumerate(self._keys):
            try:
                http = await self._get_http()
                resp = await http.get(
                    f"{self.base_url}/../api/version",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10.0,
                )
                results[f"key_{i+1}"] = {
                    "status": "ok" if resp.status_code == 200 else f"error_{resp.status_code}",
                }
            except Exception as e:
                results[f"key_{i+1}"] = {"status": "error", "message": str(e)}
        return results
