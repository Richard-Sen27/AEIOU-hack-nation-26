from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from backend.db.models import GRAPH_TABLES, USER_TABLES, Base
from backend.fixtures.load import read_fixture

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _ignore_manual(obj, name, type_, reflected, compare_to):
    return not (type_ == "index" and reflected and compare_to is None)


def test_migrations_at_head_and_match_models(test_db):
    engine = create_engine(test_db.url("atlas_owner", "postgresql+psycopg"))
    head = ScriptDirectory(str(BACKEND_DIR / "migrations")).get_current_head()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"include_object": _ignore_manual})
        assert ctx.get_current_revision() == head
        assert compare_metadata(ctx, Base.metadata) == []
    engine.dispose()


async def test_schema_objects(connect_as):
    su = await connect_as("atlas")
    exts = {r["extname"] for r in await su.fetch("SELECT extname FROM pg_extension")}
    assert {"vector", "pg_trgm", "unaccent"} <= exts
    rls = {
        r["relname"]: (r["relrowsecurity"], r["relforcerowsecurity"])
        for r in await su.fetch(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'"
        )
    }
    for table in USER_TABLES:
        assert rls[table] == (True, True), table
    for table in GRAPH_TABLES:
        assert rls[table] == (False, False), table
    indexes = {r["indexname"] for r in await su.fetch("SELECT indexname FROM pg_indexes")}
    assert {"ix_nodes_embedding_hnsw", "ix_node_synonyms_synonym_trgm", "ix_nodes_label_trgm"} <= (
        indexes
    )
    assert await su.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = 'staging'") == 1
    bypass = await su.fetchval(
        "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'atlas\\_%' AND rolbypassrls"
    )
    assert bypass == 0


async def test_fixture_loaded(connect_as):
    data = read_fixture()
    app = await connect_as("atlas_app")
    assert await app.fetchval("SELECT count(*) FROM nodes") == len(data["nodes"])
    assert await app.fetchval("SELECT count(*) FROM edges") == len(data["edges"])
    assert await app.fetchval("SELECT count(*) FROM explanations_cache") >= 4
    assert await app.fetchval("SELECT data_version FROM ingestion_runs") == "fixture"
    hit = await app.fetchval(
        "SELECT node_id FROM node_synonyms"
        " WHERE f_unaccent(lower(synonym)) % f_unaccent(lower('Ohtahara syndrom'))"
    )
    assert hit == "MONDO:9900007"


async def test_pipeline_can_write_staging_and_graph(connect_as):
    pipe = await connect_as("atlas_pipeline")
    await pipe.execute("CREATE TABLE IF NOT EXISTS staging.t_probe (x int)")
    await pipe.execute("DROP TABLE staging.t_probe")
    async with pipe.transaction():
        await pipe.execute("UPDATE nodes SET label = label WHERE id = 'HGNC:11444'")
        tr = pipe.transaction()
        await tr.start()
        await pipe.execute("TRUNCATE evidence, edges, node_synonyms, nodes, clusters")
        await tr.rollback()
