"""The one-time post-install greeting (muted message → agent sends a GIF).

`on_install` is not wired in the loader, so the plugin greets on the first
`on_load` after install, guarded by a persisted flag. These tests exercise that
once-only logic with the db flag + `ctx.send_muted_message` stubbed — no real
engine or Luna runtime required.
"""

from __future__ import annotations

import types

import pytest

from plugin_giphy import (
    _INSTALL_GREETING_NOTE,
    _INSTALL_GREETING_TITLE,
    GiphyPlugin,
)
from plugin_giphy import db


class _FakeCtx:
    def __init__(self, send):
        self.engine = object()
        self.send_muted_message = send


@pytest.fixture
def flag(monkeypatch):
    """In-memory replacement for the persisted install-greeted flag."""
    state = {"greeted": False}

    async def _was(engine):
        return state["greeted"]

    async def _mark(engine):
        state["greeted"] = True

    monkeypatch.setattr(db, "was_install_greeted", _was)
    monkeypatch.setattr(db, "mark_install_greeted", _mark)
    return state


def _recorder(result):
    calls = []

    async def _send(title, content, **kwargs):
        calls.append({"title": title, "content": content, "kwargs": kwargs})
        return result

    _send.calls = calls
    return _send


async def test_greets_once_and_lets_agent_send_a_gif(flag):
    send = _recorder({"responded": True})
    plugin = GiphyPlugin()

    sent = await plugin._greet_install_once(_FakeCtx(send))

    assert sent is True
    assert flag["greeted"] is True
    assert len(send.calls) == 1
    call = send.calls[0]
    assert call["title"] == _INSTALL_GREETING_TITLE
    assert call["kwargs"].get("respond") is True
    # The reply turn must be allowed the send_gif tool so a GIF actually lands.
    assert "send_gif" in (call["kwargs"].get("tools") or [])


async def test_does_not_greet_twice(flag):
    send = _recorder({"responded": True})
    plugin = GiphyPlugin()

    assert await plugin._greet_install_once(_FakeCtx(send)) is True
    assert await plugin._greet_install_once(_FakeCtx(send)) is False
    assert len(send.calls) == 1


async def test_retries_when_no_conversation(flag):
    send = _recorder({"error": "no target conversation", "responded": False})
    plugin = GiphyPlugin()

    sent = await plugin._greet_install_once(_FakeCtx(send))

    assert sent is False
    assert flag["greeted"] is False  # will retry next boot
    assert len(send.calls) == 1


async def test_noop_when_context_lacks_muted_channel(flag):
    ctx = types.SimpleNamespace(engine=object())  # no send_muted_message
    plugin = GiphyPlugin()

    assert await plugin._greet_install_once(ctx) is False
    assert flag["greeted"] is False


def test_note_prompts_a_gif():
    note = _INSTALL_GREETING_NOTE
    assert "send_gif" in note
    assert "installed" in note.lower()
