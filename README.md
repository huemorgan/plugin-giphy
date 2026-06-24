# plugin-giphy

Gives the [Luna](https://github.com/huemorgan/luna) agent a sense of timing — it
finds the right GIF on [GIPHY](https://giphy.com) and renders it **inline in the
chat** at the right moment: a celebration, a facepalm, a mind-blown, a "let's
go", a mood.

This is a **Luna plugin** built against the Luna Plugin SDK (`luna_sdk`) v0. It
imports nothing from `luna.*` — only the stable SDK surface — so it installs from
the Luna marketplace and runs without being part of Luna core.

## Install

In Luna: **Marketplace → Luna Official → plugin-giphy → Install**.

## What it does

| Tool | What it does |
|---|---|
| `send_gif(query, style="best", rating="pg-13")` | Find the best-matching GIF and show it **inline** in the chat. `style="random"` for variety. One call = GIF in chat. |
| `search_gifs(query, limit=5, rating="pg-13")` | Return candidate GIFs to pick from (`title`, `gif_url`, `preview_url`, `giphy_page`). |
| `send_gif_by_url(gif_url, caption=None)` | Render one specific GIF inline (e.g. one chosen from `search_gifs`). |

```
send_gif(query="mind blown")                 # → GIF appears in the chat
search_gifs(query="cat typing", limit=5)     # → list of candidates
send_gif_by_url(gif_url="https://media.giphy.com/.../giphy.gif", caption="this is us")
```

## How it renders in chat

A tool result that carries an `embed_iframe` (a self-contained HTML document) is
rendered inline by Luna — the same in-chat render hook `plugin-charts` uses. The
embed always shows a **"Powered by GIPHY"** mark, per GIPHY's attribution terms.

## API key

GIPHY requires an API key. Set a **free** one (takes a minute) for reliable use.
Resolution order:

1. vault credential `giphy_api_key`
2. env `LUNA_GIPHY_API_KEY`
3. GIPHY's old public beta key (fallback — heavily rate-limited / often banned)

Get a free key at <https://developers.giphy.com>. If no valid key is configured,
the tools return a clear, actionable error telling you to add one — so the agent
relays exactly what to do instead of silently failing.

## Layout

```
plugin_giphy/
  __init__.py        # the plugin: registers the 3 tools (luna_sdk only)
  giphy.py           # GIPHY REST client (translate / search / random), never raises
  render.py          # builds the inline embed HTML (img + "Powered by GIPHY")
  luna-plugin.toml   # the data manifest the marketplace reads
```

## Develop / test

```bash
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest -q
```

## License

MIT — see [LICENSE](./LICENSE).
