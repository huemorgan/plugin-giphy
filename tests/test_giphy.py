"""Unit tests for plugin-giphy — the inner loop, no Luna runtime needed.

Manifest tests read the TOML data contract directly. Logic tests exercise the
GIPHY client via httpx.MockTransport (no real network). Tool-wiring tests load
the plugin against a fake context and monkeypatch the GIPHY client.

Run: `pip install -e ".[dev]" && pytest`
"""

from __future__ import annotations

import asyncio
import re
import tomllib
from pathlib import Path

import httpx
import pytest

from plugin_giphy import GiphyPlugin
from plugin_giphy import giphy as giphy_mod
from plugin_giphy.render import render_gif_embed

PKG = Path(__file__).resolve().parents[1] / "plugin_giphy"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _manifest() -> dict:
    return tomllib.loads((PKG / "luna-plugin.toml").read_text())


def _gif_payload(gid: str = "abc", title: str = "Party") -> dict:
    return {
        "id": gid,
        "title": title,
        "url": f"https://giphy.com/gifs/{gid}",
        "images": {
            "downsized": {"url": f"https://media.giphy.com/{gid}/downsized.gif"},
            "original": {"url": f"https://media.giphy.com/{gid}/original.gif"},
            "fixed_height_small": {"url": f"https://media.giphy.com/{gid}/small.gif"},
        },
    }


# ---------------- manifest / data contract ----------------
def test_identity() -> None:
    m = _manifest()
    assert m["name"] == "plugin-giphy"
    assert m["entry"] == "plugin_giphy"
    assert m["sdk_version"] == "0"


def test_tool_count_matches_requires() -> None:
    m = _manifest()
    assert len(m["tools"]) == m["requires"]["tools"] == 3
    names = {t["name"] for t in m["tools"]}
    assert names == {"send_gif", "search_gifs", "send_gif_by_url"}


def test_manifest_and_code_versions_agree() -> None:
    toml_version = _manifest()["version"]
    init_src = (PKG / "__init__.py").read_text()
    code_version = re.search(r'version="([^"]+)"', init_src).group(1)
    assert toml_version == code_version


def test_manifest_matches_code_identity() -> None:
    assert GiphyPlugin.manifest.name == _manifest()["name"]
    assert GiphyPlugin.manifest.version == _manifest()["version"]


def test_no_core_imports_in_source() -> None:
    for py in PKG.rglob("*.py"):
        for line in py.read_text().splitlines():
            s = line.strip()
            if s.startswith(("import luna", "from luna")) and "luna_sdk" not in s:
                raise AssertionError(f"{py.name}: forbidden core import: {s}")


# ---------------- fake context + tool wiring ----------------
class _FakeToolRegistry:
    def __init__(self) -> None:
        self.tools: dict = {}

    def register(self, plugin_name, tool_def, handler, **kwargs) -> None:
        self.tools[tool_def.name] = handler


class _FakeContext:
    def __init__(self) -> None:
        self.tool_registry = _FakeToolRegistry()
        self.vault = None
        self.skill_registry = None
        self.events = None

    def get_env(self, _name: str) -> str | None:
        return None


def _load() -> _FakeContext:
    ctx = _FakeContext()
    asyncio.run(GiphyPlugin().on_load(ctx))
    return ctx


def test_registers_all_three_tools() -> None:
    ctx = _load()
    assert set(ctx.tool_registry.tools) == {"send_gif", "search_gifs", "send_gif_by_url"}


def test_credential_slot_declares_giphy_key() -> None:
    slots = GiphyPlugin().credential_slots()
    assert slots[0].credential_name == "giphy_api_key"
    assert slots[0].env_key_var == "LUNA_GIPHY_API_KEY"


# ---------------- render ----------------
def test_embed_contains_gif_and_attribution() -> None:
    html = render_gif_embed(
        "https://media.giphy.com/x/original.gif", title="Party", source_url="https://giphy.com/gifs/x"
    )
    assert "https://media.giphy.com/x/original.gif" in html
    assert "GIPHY" in html  # required attribution
    assert "<img" in html


def test_embed_escapes_caption() -> None:
    html = render_gif_embed("https://x/y.gif", caption="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ---------------- giphy client logic ----------------
@pytest.mark.asyncio
class TestGiphyClient:
    async def test_translate_returns_shaped_gif(self) -> None:
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            return httpx.Response(200, json={"data": _gif_payload()})

        out = await giphy_mod.translate("party", client=_client(handler), api_key="k")
        assert out["gif_url"] == "https://media.giphy.com/abc/downsized.gif"
        assert out["title"] == "Party"
        assert out["giphy_page"] == "https://giphy.com/gifs/abc"
        assert "translate" in seen["url"] and "s=party" in seen["url"]

    async def test_translate_empty_query(self) -> None:
        out = await giphy_mod.translate("   ", api_key="k")
        assert out["error"] == "empty query"

    async def test_translate_no_match(self) -> None:
        out = await giphy_mod.translate(
            "zzz", client=_client(lambda r: httpx.Response(200, json={"data": {}})), api_key="k"
        )
        assert out["error"] == "no match"

    async def test_search_returns_results(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [_gif_payload("a"), _gif_payload("b")]})

        out = await giphy_mod.search("cats", limit=2, client=_client(handler), api_key="k")
        assert out["count"] == 2
        assert out["results"][0]["gif_url"].endswith("downsized.gif")

    async def test_search_limit_clamped(self) -> None:
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            return httpx.Response(200, json={"data": []})

        await giphy_mod.search("x", limit=999, client=_client(handler), api_key="k")
        assert "limit=10" in seen["url"]

    async def test_random_returns_gif(self) -> None:
        out = await giphy_mod.random(
            "win", client=_client(lambda r: httpx.Response(200, json={"data": _gif_payload("r")})), api_key="k"
        )
        assert out["gif_url"].endswith("downsized.gif")

    async def test_auth_failure_is_reported(self) -> None:
        out = await giphy_mod.translate(
            "x", client=_client(lambda r: httpx.Response(403, text="nope")), api_key="bad"
        )
        assert out["error"] == "giphy auth failed"

    async def test_tunneled_banned_meta_status_is_auth_error(self) -> None:
        # GIPHY returns HTTP 200 with meta.status 403 "BANNED" for a bad key.
        banned = {"data": [], "meta": {"status": 403, "msg": "BANNED"}}
        out = await giphy_mod.search(
            "x", client=_client(lambda r: httpx.Response(200, json=banned)), api_key="bad"
        )
        assert out["error"] == "giphy auth failed"
        assert "developers.giphy.com" in out["detail"]

    async def test_network_error_is_caught(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        out = await giphy_mod.search("x", client=_client(handler), api_key="k")
        assert out["error"] == "request failed"

    async def test_rating_defaults_to_pg13(self) -> None:
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            return httpx.Response(200, json={"data": _gif_payload()})

        await giphy_mod.translate("x", rating="bogus", client=_client(handler), api_key="k")
        assert "rating=pg-13" in seen["url"]


# ---------------- tool handlers (wiring) ----------------
@pytest.mark.asyncio
class TestToolHandlers:
    async def test_send_gif_returns_embed(self, monkeypatch) -> None:
        async def fake_translate(query, **kwargs):
            return {
                "title": "Yay",
                "gif_url": "https://media.giphy.com/x/downsized.gif",
                "giphy_page": "https://giphy.com/gifs/x",
            }

        monkeypatch.setattr(giphy_mod, "translate", fake_translate)
        ctx = _FakeContext()
        await GiphyPlugin().on_load(ctx)
        out = await ctx.tool_registry.tools["send_gif"](query="celebrate")
        assert out["sent"] is True
        assert "embed_iframe" in out
        assert "downsized.gif" in out["embed_iframe"]

    async def test_send_gif_relays_error(self, monkeypatch) -> None:
        async def fake_translate(query, **kwargs):
            return {"error": "no match", "detail": "nothing"}

        monkeypatch.setattr(giphy_mod, "translate", fake_translate)
        ctx = _FakeContext()
        await GiphyPlugin().on_load(ctx)
        out = await ctx.tool_registry.tools["send_gif"](query="zzz")
        assert out["error"] == "no match"
        assert "embed_iframe" not in out

    async def test_send_gif_by_url_renders(self) -> None:
        ctx = _FakeContext()
        await GiphyPlugin().on_load(ctx)
        out = await ctx.tool_registry.tools["send_gif_by_url"](
            gif_url="https://media.giphy.com/y/giphy.gif", caption="us"
        )
        assert out["sent"] is True
        assert "giphy.gif" in out["embed_iframe"]

    async def test_send_gif_by_url_empty(self) -> None:
        ctx = _FakeContext()
        await GiphyPlugin().on_load(ctx)
        out = await ctx.tool_registry.tools["send_gif_by_url"](gif_url="  ")
        assert out["error"] == "empty url"
