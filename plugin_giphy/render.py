"""Build the inline chat embed for a GIF.

Luna renders a tool result's `embed_iframe` (a self-contained HTML document)
directly in the conversation — the same hook `plugin-charts` uses. So pushing a
GIF into chat is: hand back an HTML doc whose body is the `<img>`.

GIPHY's terms require visible attribution wherever GIFs are displayed, so the
embed always carries a "Powered by GIPHY" mark.
"""

from __future__ import annotations

import html as _html

_GIPHY_MARK = (
    "<svg viewBox='0 0 100 24' width='74' height='18' role='img' "
    "aria-label='Powered by GIPHY' style='vertical-align:middle'>"
    "<rect width='100' height='24' rx='4' fill='#000'/>"
    "<rect x='6' y='6' width='3' height='12' fill='#00ff99'/>"
    "<rect x='9' y='6' width='3' height='12' fill='#9933ff'/>"
    "<rect x='12' y='6' width='3' height='12' fill='#00ccff'/>"
    "<rect x='15' y='6' width='3' height='12' fill='#fff35c'/>"
    "<rect x='18' y='6' width='3' height='12' fill='#ff6666'/>"
    "<text x='27' y='16' font-family='system-ui,sans-serif' font-size='11' "
    "font-weight='700' fill='#fff'>GIPHY</text></svg>"
)

_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0f0f1a;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 12px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }}
  .gif-wrap {{
    width: 100%;
    max-width: 420px;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 6px 24px rgba(0,0,0,0.4);
    background: #1a1a2e;
  }}
  .gif-wrap img {{ display: block; width: 100%; height: auto; }}
  .meta {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    max-width: 420px;
    gap: 8px;
  }}
  .caption {{ color: #a0a0b8; font-size: 12px; line-height: 1.3; }}
  .attr {{ opacity: 0.85; flex-shrink: 0; }}
  .attr a {{ text-decoration: none; }}
</style>
</head>
<body>
  <div class="gif-wrap">
    <a href="{page}" target="_blank" rel="noopener">
      <img src="{gif}" alt="{alt}" loading="lazy">
    </a>
  </div>
  <div class="meta">
    <span class="caption">{caption}</span>
    <span class="attr"><a href="https://giphy.com" target="_blank" rel="noopener">{mark}</a></span>
  </div>
</body>
</html>"""


def render_gif_embed(
    gif_url: str,
    *,
    title: str | None = None,
    source_url: str | None = None,
    caption: str | None = None,
) -> str:
    """Return a self-contained HTML document that shows the GIF inline."""
    text = caption if caption is not None else (title or "")
    return _TEMPLATE.format(
        gif=_html.escape(gif_url, quote=True),
        page=_html.escape(source_url or "https://giphy.com", quote=True),
        alt=_html.escape(title or "GIF", quote=True),
        caption=_html.escape(text),
        mark=_GIPHY_MARK,
    )
