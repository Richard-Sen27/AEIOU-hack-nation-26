"""Connector registry: every module in this package that exposes ``SOURCE`` is a source."""

from __future__ import annotations

import importlib
import logging
import pkgutil

from pipeline.contracts import Source

log = logging.getLogger(__name__)


def all_sources() -> dict[str, Source]:
    found: dict[str, Source] = {}
    for mod in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if mod.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{mod.name}")
        except Exception:
            log.exception("source module %s failed to import; skipping it", mod.name)
            continue
        source = getattr(module, "SOURCE", None)
        if isinstance(source, Source):
            found[source.name] = source
    return found


def get_source(name: str) -> Source:
    sources = all_sources()
    if name not in sources:
        raise KeyError(f"unknown source {name!r}; known: {', '.join(sorted(sources))}")
    return sources[name]
