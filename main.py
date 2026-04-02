import os
from datetime import datetime, timezone
from typing import Any

import httpx
import jwt
from fastapi import Cookie, FastAPI, HTTPException
from pydantic import BaseModel


PORT = int(os.getenv("BANK_PORT", "8003"))
MEMORY_URL = os.getenv("MEMORY_URL", "http://inmemory:8005")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
COOKIE_NAME = os.getenv("AUTH_COOKIE", "bezum_jwt")
FLAG_BANK_SSRF = os.getenv("FLAG_BANK_SSRF", "flag{placeholder}")

SHOP = [
    {"id": "hat-spark", "title": "Spark Hat", "price": 45, "color": "rbpink"},
    {"id": "jacket-navy", "title": "Navy Jacket", "price": 80, "color": "rbnavy"},
    {"id": "badge-cinema", "title": "Cinema Badge", "price": 120, "color": "rforange"},
]

app = FastAPI(title="Bezum Bank")


class TransferPayload(BaseModel):
    toUserId: str
    amount: int


class RewardPayload(BaseModel):
    amount: int


class BuyPayload(BaseModel):
    itemId: str


class PreviewPayload(BaseModel):
    url: str


async def memory_get(path: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{MEMORY_URL}{path}")
        response.raise_for_status()
        return response.json()


async def memory_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{MEMORY_URL}{path}", json=payload)
        response.raise_for_status()
        return response.json()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def user_id_from_cookie(token: str | None) -> str:
    if not token:
        raise HTTPException(status_code=401, detail="Auth required.")
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return claims["user"]["id"]
    except Exception as exc:  # intended weak model, strict enough only for signature
        raise HTTPException(status_code=401, detail="Auth required.") from exc


async def wallets() -> list[dict[str, Any]]:
    payload = await memory_get("/api/buckets/wallets")
    return payload.get("items", [])


async def save_wallet(wallet: dict[str, Any]) -> dict[str, Any]:
    payload = await memory_post("/api/buckets/wallets", wallet)
    return payload.get("item", wallet)


async def wallet_for(user_id: str) -> dict[str, Any]:
    for wallet in await wallets():
        if wallet.get("userId") == user_id:
            return wallet
    wallet = {
        "id": f"wallet-{user_id}",
        "userId": user_id,
        "balance": 175,
        "inventory": ["starter-pass"],
        "updatedAt": now_iso(),
    }
    return await save_wallet(wallet)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "bank-fastapi"}


@app.get("/api/bank/me")
async def bank_me(bezum_jwt: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
    user_id = user_id_from_cookie(bezum_jwt)
    return {"ok": True, "wallet": await wallet_for(user_id)}


@app.get("/api/bank/shop")
async def bank_shop(bezum_jwt: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
    user_id_from_cookie(bezum_jwt)
    return {"ok": True, "shop": SHOP}


@app.post("/api/bank/buy")
async def bank_buy(payload: BuyPayload, bezum_jwt: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
    user_id = user_id_from_cookie(bezum_jwt)
    wallet = await wallet_for(user_id)
    item = next((entry for entry in SHOP if entry["id"] == payload.itemId), None)
    if not item:
        raise HTTPException(status_code=404, detail="No item.")
    if item["id"] in wallet["inventory"]:
        raise HTTPException(status_code=409, detail="Already bought.")
    if wallet["balance"] < item["price"]:
        raise HTTPException(status_code=402, detail="No coins.")
    wallet["balance"] -= item["price"]
    wallet["inventory"].append(item["id"])
    wallet["updatedAt"] = now_iso()
    wallet = await save_wallet(wallet)
    return {"ok": True, "wallet": wallet, "item": item}


@app.post("/api/bank/reward")
async def bank_reward(payload: RewardPayload, bezum_jwt: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
    user_id = user_id_from_cookie(bezum_jwt)
    wallet = await wallet_for(user_id)
    amount = max(1, min(250, int(payload.amount)))
    wallet["balance"] += amount
    wallet["updatedAt"] = now_iso()
    wallet = await save_wallet(wallet)
    return {"ok": True, "wallet": wallet, "amount": amount}


@app.post("/api/bank/transfer")
async def bank_transfer(payload: TransferPayload, bezum_jwt: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
    user_id = user_id_from_cookie(bezum_jwt)
    amount = max(1, min(300, int(payload.amount)))
    if not payload.toUserId or payload.toUserId == user_id:
        raise HTTPException(status_code=400, detail="Bad target.")
    wallet = await wallet_for(user_id)
    if wallet["balance"] < amount:
        raise HTTPException(status_code=400, detail="No coins.")
    other = await wallet_for(payload.toUserId)
    wallet["balance"] -= amount
    wallet["updatedAt"] = now_iso()
    other["balance"] += amount
    other["updatedAt"] = now_iso()
    await save_wallet(wallet)
    await save_wallet(other)
    return {"ok": True, "wallet": wallet, "amount": amount}


@app.post("/api/bank/preview")
async def bank_preview(payload: PreviewPayload, bezum_jwt: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict[str, Any]:
    user_id_from_cookie(bezum_jwt)
    if not payload.url.startswith("http://") and not payload.url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Bad url.")
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(payload.url)
    return {
        "ok": True,
        "target": payload.url,
        "status": response.status_code,
        "preview": response.text[:500],
        "hint": FLAG_BANK_SSRF,
    }
