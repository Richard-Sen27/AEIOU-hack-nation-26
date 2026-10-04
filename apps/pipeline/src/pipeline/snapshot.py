"""Stage 7b: export the final graph as a snapshot (Parquet + manifest)."""

from __future__ import annotations

import json
import logging
import shutil
from typing import Any

from pipeline.build import FINAL, read_graph, require_validated
from pipeline.config import settings
from pipeline.contracts import load_scope, now_iso, sha256_file
from pipeline.load import pipeline_commit, source_versions
from pipeline.paths import SNAPSHOT

log = logging.getLogger(__name__)

TABLES = ("nodes", "synonyms", "edges", "evidence", "clusters", "mechanisms", "hpo_terms")


def run() -> dict[str, Any]:
    tables = read_graph(FINAL)
    version = require_validated(tables)
    out = SNAPSHOT / version
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in TABLES:
        if name not in tables:
            continue
        dst = out / f"{name}.parquet"
        shutil.copyfile(FINAL / f"{name}.parquet", dst)
        files[dst.name] = {"sha256": sha256_file(dst), "rows": tables[name].height}
    summary = json.loads((FINAL / "summary.json").read_text())
    validation_file = FINAL / "validation.json"
    validation = json.loads(validation_file.read_text()) if validation_file.exists() else {}
    scope = load_scope(required=False)
    manifest = {
        "data_version": version,
        "created_at": now_iso(),
        "pipeline_commit": pipeline_commit() or None,
        "scope": {
            "data_version": scope.data_version if scope else None,
            "genes": len(scope.genes) if scope else 0,
            "diseases": len(scope.diseases) if scope else 0,
            "phenotypes": len(scope.phenotypes) if scope else 0,
        },
        "thresholds": {
            "researcher_min_links": settings.researcher_min_links,
            "confidence_supported": 0.6,
        },
        "counts": summary,
        "validation_ok": validation.get("ok"),
        "quote_verification": {
            k: v
            for k, v in (validation.get("quote_verification") or {}).items()
            if k != "by_extractor"
        },
        "files": files,
        "source_versions": source_versions(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    latest = SNAPSHOT / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(out.name)
    log.info("snapshot %s written to %s", version, out)
    return manifest
