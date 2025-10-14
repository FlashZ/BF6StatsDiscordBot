"""
Async wrapper for tracker.gg BF-6 endpoints.
• Cloudflare solved with cloudscraper
• 30-second in-memory cache (bypass with fresh=True)
"""

from __future__ import annotations
import os, asyncio, typing as t, time, logging, cloudscraper, requests

log         = logging.getLogger("bf6bot.trn")
BASE        = "https://api.tracker.gg/api/v2/bf6/standard"
TRN_API_KEY = os.getenv("TRN_API_KEY", "")
HEADERS     = {"TRN-Api-Key": TRN_API_KEY}

_scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True}
)
_scraper.cookies.set("cf_clearance", os.getenv("CF_CLEARANCE", ""))
_scraper.cookies.set("__cf_bm",      os.getenv("CF_BM",       ""))

_CONCURRENCY = asyncio.Semaphore(4)
_TTL         = 30          # seconds
_CACHE: dict[str, tuple[float, dict]] = {}   # key → (timestamp, data)


def _key(url: str, params: dict | None) -> str:
    if not params:
        return url
    p = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{url}?{p}"


async def _fetch(url: str, *, params: dict | None = None, fresh=False) -> dict | None:
    """Return `payload["data"]` or None.  403 => solve Cloudflare once."""
    cache_k = _key(url, params)
    now     = time.time()

    if not fresh and cache_k in _CACHE:
        ts, data = _CACHE[cache_k]
        if now - ts < _TTL:
            return data

    async with _CONCURRENCY:
        for attempt in (1, 2):
            try:
                r = _scraper.get(url, params=params, headers=HEADERS, timeout=15)
                if r.status_code == 403 and attempt == 1:
                    log.warning("[TRN] 403 → solving CF challenge %s", url)
                    _scraper.solve_cloudflare(url)
                    continue
                r.raise_for_status()
                data = r.json()["data"]
                _CACHE[cache_k] = (now, data)
                return data
            except requests.RequestException as e:
                log.warning("[TRN] %s (attempt %s/2)", e, attempt)
        return None


# ──────────────────────────────────────────────────────────────────────────
class TrnClient:
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False

    # keep the `fresh` kwarg so main.py doesn’t have to change
    async def player_profile(
        self, platform: str, user_id: str, *, fresh: bool = False
    ) -> dict | None:
        return await _fetch(f"{BASE}/profile/{platform}/{user_id}", fresh=fresh)

    async def recent_matches(
        self, platform: str, user_id: str, limit: int = 5
    ) -> list[dict]:
        data = await _fetch(
            f"{BASE}/matches/{platform}/{user_id}",
            params={"page": 1, "limit": limit}
        )

        # ── normalise shape ───────────────────────────────
        if data is None:
            return []

        if isinstance(data, list):               # ← bare list variant
            return data[:limit]

        return data.get("matches", [])

    async def search_player(self, platform: str, query: str) -> t.Optional[dict]:
        """
        Tracker sometimes responds with *list* (legacy) and sometimes with the
        usual {"matches":[…]} blob.  Normalise both forms.
        """
        data = await _fetch(
            f"{BASE}/search",
            params=dict(platform=platform, query=query, autocomplete="true")
        )

        # legacy: bare list ▸ wrap it
        if isinstance(data, list):
            return data[0] if data else None
        # normal shape
        if data and data.get("matches"):
            return data["matches"][0]
        return None
