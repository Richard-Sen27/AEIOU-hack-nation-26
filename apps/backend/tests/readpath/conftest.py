import json
import uuid
from pathlib import Path

import pytest

from backend.api.services import graph as graph_service
from backend.db.session import user_transaction

DEMO = json.loads(
    (Path(graph_service.__file__).parents[2] / "fixtures" / "demo_graph.json").read_text()
)["demo"]


@pytest.fixture
async def restore_graph(app):
    """Snapshot the in-memory store and reinstall it after the test."""
    store = graph_service.get_graph()
    yield store
    graph_service.set_graph(store)


async def refresh_overlays() -> None:
    async with user_transaction(None) as db:
        await graph_service.refresh_flags(db)
        await graph_service.refresh_contributions(db)


async def as_user(connect_as, user_id: uuid.UUID, sql: str, *args):
    conn = await connect_as("atlas_app")
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.user_id', $1, true)", str(user_id))
        return await conn.fetch(sql, *args)
