from fastapi import FastAPI

app = FastAPI(title="Rare Disease Atlas API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
