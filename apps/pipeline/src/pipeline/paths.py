from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
NORMALIZED = DATA / "normalized"
EXTRACTED = DATA / "extracted"
GRAPH = DATA / "graph"
SNAPSHOT = DATA / "snapshot"
CACHE = DATA / "cache"
SCOPE_DIR = DATA / "scope"
SCOPE_FILE = SCOPE_DIR / "scope.json"
LOGS = DATA / "logs"

SEEDS_FILE = ROOT / "seeds.yaml"
CURATED = ROOT / "curated"
