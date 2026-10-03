"""`atlas-pipeline`: one Typer command per pipeline stage (mirrored by the Makefile targets)."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import subprocess
import sys
import time
from typing import Annotated

import typer

from pipeline.contracts import load_scope
from pipeline.paths import ROOT
from pipeline.sources import all_sources, get_source

app = typer.Typer(no_args_is_help=True, add_completion=False)
log = logging.getLogger("pipeline")

SourceOpt = Annotated[list[str] | None, typer.Option("--source", "-s", help="Only this source")]
PhaseOpt = Annotated[str | None, typer.Option("--phase", help="bulk | scoped")]


@app.callback()
def _setup(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "hishel", "anysqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _run(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return result


def _timed(name: str):
    class _T:
        def __enter__(self):
            self.t = time.perf_counter()
            log.info("== %s ==", name)

        def __exit__(self, *exc):
            if exc[0] is None:
                log.info("== %s done in %.1fs ==", name, time.perf_counter() - self.t)

    return _T()


def _selected(names: list[str] | None, phase: str | None):
    sources = all_sources()
    if names:
        chosen = [get_source(n) for n in names]
    else:
        chosen = list(sources.values())
    if phase:
        chosen = [s for s in chosen if s.phase == phase]
    return chosen


@app.command()
def scope() -> None:
    """Stage 0: resolve seeds.yaml into data/scope/scope.json."""
    from pipeline import scope as stage

    with _timed("scope"):
        stage.run()


@app.command()
def fetch(source: SourceOpt = None, phase: PhaseOpt = None) -> None:
    """Stage 1: download raw data. Scoped sources run only once scope.json exists."""
    chosen = _selected(source, phase)
    scope_obj = load_scope(required=False)

    async def go():
        for s in [s for s in chosen if s.phase == "bulk"]:
            with _timed(f"fetch {s.name}"):
                await s.fetch(scope_obj)
        scoped = [s for s in chosen if s.phase == "scoped"]
        if scoped and scope_obj is None:
            log.warning("no scope yet; skipping scoped sources %s", [s.name for s in scoped])
            return
        for s in scoped:
            with _timed(f"fetch {s.name}"):
                await s.fetch(scope_obj)

    asyncio.run(go())


@app.command()
def normalize(source: SourceOpt = None) -> None:
    """Stage 2: parse raw data into the contract tables under data/normalized/<source>/."""
    scope_obj = load_scope()
    for s in _selected(source, None):
        with _timed(f"normalize {s.name}"):
            _run(s.normalize, scope_obj)
    from pipeline import linking

    with _timed("linking"):
        _run(linking.run, scope_obj)


@app.command()
def extract() -> None:
    """Stage 3: LLM extraction (pipeline.extract.run, owned by the literature agent)."""
    try:
        module = importlib.import_module("pipeline.extract")
    except ModuleNotFoundError:
        log.warning("pipeline.extract not available; skipping Stage 3")
        return
    with _timed("extract"):
        _run(module.run)


@app.command()
def build() -> None:
    """Stage 4: merge assertions into edges + evidence with confidence."""
    from pipeline import build as stage

    with _timed("build"):
        stage.run()


@app.command()
def analytics() -> None:
    """Stage 5: similarity, mechanism inference, clustering, layout, centrality."""
    from pipeline import analytics as stage

    with _timed("analytics"):
        _run(stage.run)


@app.command()
def validate() -> None:
    """Stage 6: fail unless every check passes."""
    from pipeline import validate as stage

    with _timed("validate"):
        ok = stage.run()
    if not ok:
        raise typer.Exit(1)


@app.command()
def load() -> None:
    """Stage 7a: psql \\copy into staging, promote into the graph tables."""
    from pipeline import load as stage

    with _timed("load"):
        stage.run()


@app.command()
def snapshot() -> None:
    """Stage 7b: export Parquet + manifest."""
    from pipeline import snapshot as stage

    with _timed("snapshot"):
        stage.run()


@app.command()
def explain() -> None:
    """Pre-generate explanations for demo paths (backend CLI)."""
    cmd = [sys.executable, "-m", "backend.cli", "precompute-explanations"]
    cmd += ["--language", "en", "--language", "de"]
    # The backend reads its own .env relative to the working directory (repo layout only).
    backend_dir = ROOT.parent / "backend"
    with _timed("explain"):
        proc = subprocess.run(cmd, cwd=backend_dir if backend_dir.is_dir() else None)
        if proc.returncode != 0:
            log.warning(
                "backend.cli precompute-explanations unavailable or failed (exit %s); "
                "explanations not precomputed",
                proc.returncode,
            )


@app.command()
def login() -> None:
    """Sign in with ChatGPT once so LLM steps run on your plan (pipeline.llm.login)."""
    try:
        llm = importlib.import_module("pipeline.llm")
    except ModuleNotFoundError:
        log.error("pipeline.llm is not available yet")
        raise typer.Exit(1) from None
    _run(llm.login)


@app.command()
def logout() -> None:
    """Forget the stored ChatGPT sign-in (pipeline.llm.logout)."""
    _llm_call("logout")


@app.command()
def whoami() -> None:
    """Show who is signed in for the pipeline's LLM steps (pipeline.llm.whoami)."""
    _llm_call("whoami")


def _llm_call(name: str) -> None:
    try:
        llm = importlib.import_module("pipeline.llm")
    except ModuleNotFoundError:
        log.error("pipeline.llm is not available")
        raise typer.Exit(1) from None
    _run(getattr(llm, name))


@app.command(name="all")
def run_all(skip_explain: Annotated[bool, typer.Option("--skip-explain")] = False) -> None:
    """fetch bulk -> scope -> fetch scoped -> normalize -> extract -> build -> analytics ->
    validate -> load -> snapshot -> explain."""
    t = time.perf_counter()
    fetch(source=None, phase="bulk")
    scope()
    fetch(source=None, phase="scoped")
    normalize(source=None)
    extract()
    build()
    analytics()
    validate()
    load()
    snapshot()
    if not skip_explain:
        explain()
    log.info("pipeline finished in %.1fs", time.perf_counter() - t)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
