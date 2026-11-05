from fastapi import FastAPI

app = FastAPI(title="StunSail API", version="0.1.0")


@app.get("/api/v1/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "api_version": "v1"}
