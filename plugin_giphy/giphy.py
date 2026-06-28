"""GIPHY REST client — find the right GIF, fast.

Pure logic against `httpx`; imports nothing from `luna_sdk` so it unit-tests
anywhere. Every function NEVER raises — it returns a result dict or an
`{"error": ...}` dict so the tool layer can relay failures to the agent.

Three lookups cover every need:
  - translate → the single best match for a phrase (the headline path)
  - search    → a ranked list of candidates to choose from
  - random    → a surprise GIF for a tag (variety)

API key resolution is the caller's job; this module just takes a key. The
GIPHY public beta key is used as a zero-config default so the plugin works
out of the box; an owner can override it via the vault or env.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

API_BASE = "https://api.giphy.com/v1/gifs"
# GIPHY's old public beta key — used only as a last-resort fallback. It is
# heavily rate-limited and frequently banned, so for reliable use an owner sets
# their own free key via vault `giphy_api_key` or env `LUNA_GIPHY_API_KEY`. When
# the fallback is rejected, the tools return an actionable "set your key" error.
PUBLIC_BETA_KEY = "dc6zaTOxFJmzC"
DEFAULT_TIMEOUT = 15.0
VALID_RATINGS = {"g", "pg", "pg-13", "r"}
USER_AGENT = "Luna/1.0 (AI Agent; +https://github.com/huemorgan/plugin-giphy)"


def _clean_rating(rating: str | None) -> str:
    r = (rating or "pg-13").strip().lower()
    return r if r in VALID_RATINGS else "pg-13"


def _pick_image_url(images: dict[str, Any]) -> str | None:
    """Choose a chat-friendly GIF url: a sized variant first, then the original.

    `downsized` keeps the chat snappy; `original` is the fallback. Always a
    `.gif`-ish media url (never the GIPHY page).
    """
    for key in ("downsized_medium", "downsized", "fixed_height", "original"):
        url = (images.get(key) or {}).get("url")
        if url:
            return url
    return None


def _shape_gif(item: dict[str, Any]) -> dict[str, Any] | None:
    """Reduce a raw GIPHY object to the fields the agent + embed need."""
    images = item.get("images") or {}
    gif_url = _pick_image_url(images)
    if not gif_url:
        return None
    preview = (
        (images.get("fixed_height_small") or {}).get("url")
        or (images.get("preview_gif") or {}).get("url")
        or gif_url
    )
    return {
        "id": item.get("id"),
        "title": (item.get("title") or "").strip() or "GIF",
        "gif_url": gif_url,
        "preview_url": preview,
        "giphy_page": item.get("url"),
    }


def resolve_base() -> tuple[str, bool]:
    """Where GIPHY traffic goes. `LUNA_GIPHY_BASE_URL` routes through a cloud
    gateway/proxy (`{gateway}/proxy/giphy`); when set the plugin sends NO api_key
    and the gateway injects the real one (query-param auth). Returns
    `(base, proxied)`. Unset → the real GIPHY API + the caller's key."""
    base = (os.environ.get("LUNA_GIPHY_BASE_URL") or "").strip()
    if not base:
        return API_BASE, False
    return base.rstrip("/"), True


def _params(api_key: str | None, **extra: Any) -> dict[str, Any]:
    # In proxy mode the caller passes api_key=None — omit it entirely so the
    # gateway can inject the real key. Otherwise send the resolved key.
    params: dict[str, Any] = {}
    if api_key:
        params["api_key"] = api_key
    params.update({k: v for k, v in extra.items() if v is not None})
    return params


_AUTH_HELP = (
    "The GIPHY API key is missing, invalid, or banned. Set your own free key "
    "(get one at https://developers.giphy.com): store it as the vault credential "
    "`giphy_api_key`, or set the env var `LUNA_GIPHY_API_KEY`, then retry."
)


def _auth_error() -> dict[str, str]:
    return {"error": "giphy auth failed", "detail": _AUTH_HELP}


async def _get(
    path: str, params: dict[str, Any], *, client: httpx.AsyncClient | None, base: str = API_BASE
) -> dict[str, Any] | list[dict[str, Any]] | dict[str, str]:
    owns = client is None
    client = client or httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}
    )
    try:
        resp = await client.get(f"{base}/{path}", params=params)
        if resp.status_code in (401, 403):
            return _auth_error()
        if resp.status_code == 429:
            return {"error": "giphy rate limited", "detail": "GIPHY rate limit hit. " + _AUTH_HELP}
        if resp.status_code >= 400:
            return {"error": "giphy request failed", "detail": f"HTTP {resp.status_code}", "status": resp.status_code}
        try:
            data = resp.json()
        except ValueError:
            return {"error": "bad response", "detail": "GIPHY did not return JSON."}
        # GIPHY tunnels auth/quota failures through the body: HTTP 200 with a
        # meta.status like 403 "BANNED" or 429. Surface those as real errors.
        meta = data.get("meta") if isinstance(data, dict) else None
        m_status = int((meta or {}).get("status", 200) or 200)
        if m_status in (401, 403):
            return _auth_error()
        if m_status == 429:
            return {"error": "giphy rate limited", "detail": "GIPHY rate limit hit. " + _AUTH_HELP}
        if m_status >= 400:
            return {
                "error": "giphy request failed",
                "detail": f"GIPHY meta status {m_status}: {(meta or {}).get('msg', '')}".strip(),
                "status": m_status,
            }
        return data
    except httpx.HTTPError as exc:
        return {"error": "request failed", "detail": str(exc)}
    finally:
        if owns:
            await client.aclose()


async def translate(
    query: str,
    *,
    rating: str | None = None,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Best single GIF for a phrase. Returns a shaped gif dict or an error dict."""
    query = (query or "").strip()
    if not query:
        return {"error": "empty query", "detail": "Provide a phrase to look up."}
    base, proxied = resolve_base()
    data = await _get(
        "translate",
        _params(None if proxied else (api_key or PUBLIC_BETA_KEY), s=query, rating=_clean_rating(rating), weirdness=0),
        client=client,
        base=base,
    )
    if isinstance(data, dict) and "error" in data:
        return data
    item = data.get("data") if isinstance(data, dict) else None
    if not item:
        return {"error": "no match", "detail": f"GIPHY found no GIF for '{query}'."}
    shaped = _shape_gif(item)
    if shaped is None:
        return {"error": "no match", "detail": f"GIPHY returned no usable image for '{query}'."}
    return shaped


async def search(
    query: str,
    *,
    limit: int = 5,
    rating: str | None = None,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Ranked candidate GIFs for a query. Returns {"results": [...]} or an error."""
    query = (query or "").strip()
    if not query:
        return {"error": "empty query", "detail": "Provide a search query."}
    limit = max(1, min(int(limit or 5), 10))
    base, proxied = resolve_base()
    data = await _get(
        "search",
        _params(None if proxied else (api_key or PUBLIC_BETA_KEY), q=query, limit=limit, rating=_clean_rating(rating), lang="en"),
        client=client,
        base=base,
    )
    if isinstance(data, dict) and "error" in data:
        return data
    items = data.get("data") if isinstance(data, dict) else None
    if not items:
        return {"error": "no match", "detail": f"GIPHY found no GIFs for '{query}'.", "results": []}
    results = [s for s in (_shape_gif(it) for it in items) if s is not None]
    return {"query": query, "count": len(results), "results": results}


async def random(
    tag: str,
    *,
    rating: str | None = None,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """A random GIF for a tag. Returns a shaped gif dict or an error dict."""
    tag = (tag or "").strip()
    base, proxied = resolve_base()
    data = await _get(
        "random",
        _params(None if proxied else (api_key or PUBLIC_BETA_KEY), tag=tag or None, rating=_clean_rating(rating)),
        client=client,
        base=base,
    )
    if isinstance(data, dict) and "error" in data:
        return data
    item = data.get("data") if isinstance(data, dict) else None
    # The random endpoint returns {} (not a list) when nothing matches a tag.
    if not item:
        return {"error": "no match", "detail": f"GIPHY found no random GIF for '{tag}'."}
    shaped = _shape_gif(item)
    if shaped is None:
        return {"error": "no match", "detail": f"GIPHY returned no usable image for '{tag}'."}
    return shaped
