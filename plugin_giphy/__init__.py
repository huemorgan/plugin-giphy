"""plugin-giphy — let the agent drop the right GIF into chat at the right moment.

Authored against `luna_sdk` ONLY (never `import luna.*`). The agent finds a GIF
on GIPHY and returns it as an `embed_iframe`, which Luna renders inline in the
conversation (the same in-chat render hook `plugin-charts` uses).

Tools:
  - send_gif        — find the best match and render it inline (one shot)
  - search_gifs     — return candidate GIFs so the agent can pick the perfect one
  - send_gif_by_url — render one specific GIF inline (e.g. chosen from search)

API key resolution (zero-config, overridable):
  vault `giphy_api_key` -> env `LUNA_GIPHY_API_KEY` -> GIPHY public beta key.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from luna_sdk import CredentialSlot, LunaPlugin, PluginContext, PluginManifest, ToolDef

from . import giphy
from .render import render_gif_embed

log = logging.getLogger("plugin-giphy")

VAULT_KEY = "giphy_api_key"
ENV_KEY = "LUNA_GIPHY_API_KEY"

_RATING_PROP = {
    "type": "string",
    "enum": ["g", "pg", "pg-13", "r"],
    "description": "Content rating ceiling (default pg-13).",
}

_SEND_GIF_DEF = ToolDef(
    name="send_gif",
    description=(
        "Find the most fitting GIF for a moment and show it INLINE in the chat. "
        "Use this to react with a GIF — celebration, facepalm, mind-blown, "
        "thumbs up, a 'let's go', a mood — whenever a GIF would land better than "
        "words, or when the user asks for a GIF/meme/reaction. `query` is the "
        "vibe or subject in plain words (e.g. 'excited celebration', 'facepalm', "
        "'cat typing'). Set style='random' for variety. The GIF renders directly "
        "in the conversation; keep any accompanying text short."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The reaction/vibe/subject in plain words, e.g. 'mind blown'.",
            },
            "style": {
                "type": "string",
                "enum": ["best", "random"],
                "description": "'best' = top match (default); 'random' = a surprising pick for variety.",
            },
            "rating": _RATING_PROP,
        },
        "required": ["query"],
    },
    policy="auto_approve",
    risk_level="low",
    timeout_seconds=20,
)

_SEARCH_GIFS_DEF = ToolDef(
    name="search_gifs",
    description=(
        "Search GIPHY and return a ranked list of candidate GIFs (title, gif_url, "
        "preview_url, giphy_page) WITHOUT showing one. Use when you want to pick "
        "the perfect GIF before sending it — then call send_gif_by_url with the "
        "chosen gif_url. Prefer send_gif when you just want to react quickly."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "limit": {
                "type": "integer",
                "description": "How many candidates to return (1-10, default 5).",
                "default": 5,
            },
            "rating": _RATING_PROP,
        },
        "required": ["query"],
    },
    policy="auto_approve",
    risk_level="low",
    timeout_seconds=20,
)

_SEND_GIF_BY_URL_DEF = ToolDef(
    name="send_gif_by_url",
    description=(
        "Show one specific GIF INLINE in the chat by its url — typically a "
        "gif_url returned by search_gifs. Use after search_gifs to send the GIF "
        "you picked. Add a short caption if helpful."
    ),
    parameters={
        "type": "object",
        "properties": {
            "gif_url": {"type": "string", "description": "Direct GIF media url (e.g. a .gif from search_gifs)."},
            "caption": {"type": "string", "description": "Optional short caption shown under the GIF."},
        },
        "required": ["gif_url"],
    },
    policy="auto_approve",
    risk_level="low",
)


class GiphyPlugin(LunaPlugin):
    manifest = PluginManifest(
        name="plugin-giphy",
        icon="film",
        image="assets/icon.png",
        version="0.2.1",
        description=(
            "Drop the right GIF into chat at the right moment — GIPHY search + "
            "inline reactions. Built on luna_sdk v0."
        ),
        tools=[_SEND_GIF_DEF, _SEARCH_GIFS_DEF, _SEND_GIF_BY_URL_DEF],
    )

    def __init__(self) -> None:
        self._ctx: PluginContext | None = None

    def credential_slots(self) -> list[CredentialSlot]:
        return [
            CredentialSlot(
                slug="giphy",
                credential_name=VAULT_KEY,
                env_key_var=ENV_KEY,
                # Advertising a base-url var marks giphy proxy-provisionable: the
                # gateway sets LUNA_GIPHY_BASE_URL and injects the real api_key
                # (query-param auth), so the plugin sends key-less requests.
                env_base_url_var="LUNA_GIPHY_BASE_URL",
                owner=self.manifest.name,
            )
        ]

    async def _api_key(self) -> str:
        """vault giphy_api_key -> env LUNA_GIPHY_API_KEY -> public beta key."""
        ctx = self._ctx
        if ctx is not None and getattr(ctx, "vault", None) is not None:
            try:
                cred = await ctx.vault.get_credential(VAULT_KEY)
                if (cred.value or "").strip():
                    return cred.value.strip()
            except KeyError:
                pass
            except Exception as exc:  # noqa: BLE001 — vault hiccup must not break a reaction
                log.warning("giphy: vault read failed: %s", exc)
        if ctx is not None and getattr(ctx, "get_env", None) is not None:
            env_val = (ctx.get_env(ENV_KEY) or "").strip()
            if env_val:
                return env_val
        return giphy.PUBLIC_BETA_KEY

    async def on_load(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        events = getattr(ctx, "events", None)

        async def _emit(name: str, payload: dict[str, Any]) -> None:
            if events is not None:
                try:
                    await events.emit(name, payload)
                except Exception:  # noqa: BLE001
                    pass

        # IMPORTANT: tool results MUST be returned as a JSON *string*. The host
        # stringifies a handler's return with str(), then the chat layer does
        # json.loads() on it to pull out `embed_iframe` and render it inline. A
        # raw dict would become a single-quoted Python repr that json.loads
        # rejects, so the GIF would never display. (Same contract as
        # plugin-charts.)
        async def _send_gif(query: str, style: str = "best", rating: str | None = None) -> str:
            key = await self._api_key()
            if style == "random":
                gif = await giphy.random(query, rating=rating, api_key=key)
            else:
                gif = await giphy.translate(query, rating=rating, api_key=key)
            await _emit("giphy.send", {"query": query, "style": style, "error": gif.get("error")})
            if "error" in gif:
                return json.dumps(gif)
            return json.dumps({
                "sent": True,
                "title": gif["title"],
                "gif_url": gif["gif_url"],
                "giphy_page": gif.get("giphy_page"),
                "embed_iframe": render_gif_embed(
                    gif["gif_url"], title=gif["title"], source_url=gif.get("giphy_page")
                ),
            })

        async def _search_gifs(query: str, limit: int = 5, rating: str | None = None) -> str:
            key = await self._api_key()
            out = await giphy.search(query, limit=limit, rating=rating, api_key=key)
            await _emit(
                "giphy.search",
                {"query": query, "count": out.get("count", 0), "error": out.get("error")},
            )
            return json.dumps(out)

        async def _send_gif_by_url(gif_url: str, caption: str | None = None) -> str:
            gif_url = (gif_url or "").strip()
            if not gif_url:
                return json.dumps({"error": "empty url", "detail": "Provide the GIF media url to show."})
            await _emit("giphy.send_url", {"gif_url": gif_url})
            return json.dumps({
                "sent": True,
                "gif_url": gif_url,
                "embed_iframe": render_gif_embed(gif_url, title=caption, caption=caption),
            })

        ctx.tool_registry.register(self.manifest.name, _SEND_GIF_DEF, _send_gif)
        ctx.tool_registry.register(self.manifest.name, _SEARCH_GIFS_DEF, _search_gifs)
        ctx.tool_registry.register(self.manifest.name, _SEND_GIF_BY_URL_DEF, _send_gif_by_url)
        log.info("giphy.tools_registered: send_gif, search_gifs, send_gif_by_url")
