"""Write the OpenAPI spec to apps/backend/openapi.json (input for the frontend's Hey API client)."""

import json
from pathlib import Path

from backend.main import app

OUT = Path(__file__).resolve().parents[1] / "openapi.json"

if __name__ == "__main__":
    OUT.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT}")
