import pytest


@pytest.fixture
async def superuser(connect_as):
    return await connect_as("atlas")


@pytest.fixture
async def edge_ids(superuser) -> list[str]:
    rows = await superuser.fetch("SELECT id FROM edges ORDER BY id LIMIT 3")
    assert rows, "fixture graph has no edges"
    return [r["id"] for r in rows]
