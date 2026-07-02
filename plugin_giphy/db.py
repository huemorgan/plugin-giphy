"""Tiny plugin-owned store for one-time flags (e.g. the post-install greeting).

Isolated table via ``luna_sdk.declarative_base()`` + ``ctx.engine`` — never
touches core's Base. GIPHY is otherwise stateless; this exists only so the
install greeting fires exactly once instead of on every boot.
"""

from __future__ import annotations

from sqlalchemy import String, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from luna_sdk import declarative_base

Base = declarative_base()


class GiphyMeta(Base):
    __tablename__ = "giphy_plugin_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))


_M = GiphyMeta.__table__

# Marks that the post-install greeting has already been delivered once.
_INSTALL_GREETED_KEY = "install_greeted"


async def create_tables(engine) -> None:
    async with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            await conn.run_sync(table.create, checkfirst=True)


async def was_install_greeted(engine) -> bool:
    """True once the one-time post-install greeting has been recorded."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(_M.c.value).where(_M.c.key == _INSTALL_GREETED_KEY).limit(1)
            )
        ).first()
    return row is not None


async def mark_install_greeted(engine) -> None:
    """Record that the post-install greeting was delivered (idempotent)."""
    async with engine.begin() as conn:
        exists = (
            await conn.execute(
                select(_M.c.key).where(_M.c.key == _INSTALL_GREETED_KEY).limit(1)
            )
        ).first()
        if exists is None:
            await conn.execute(insert(_M).values(key=_INSTALL_GREETED_KEY, value="1"))
