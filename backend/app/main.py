from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Investment Intelligence API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "investment-intelligence-api"}


@app.get("/api/assets/examples")
def example_assets() -> list[dict[str, str]]:
    return [
        {"symbol": "MSFT", "name": "Microsoft", "market": "NASDAQ", "currency": "USD"},
        {"symbol": "ASML", "name": "ASML Holding", "market": "Euronext Amsterdam", "currency": "EUR"},
        {"symbol": "ACCESS", "name": "Access Bank Ghana", "market": "GSE", "currency": "GHS"},
    ]
