import json
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

EVOLUTION_API_URL = os.environ["EVOLUTION_API_URL"]
EVOLUTION_API_KEY = os.environ["EVOLUTION_API_KEY"]
EVOLUTION_INSTANCE = os.environ["EVOLUTION_INSTANCE"]

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_API_TOKEN = os.environ["MONDAY_API_TOKEN"]
MONDAY_BOARD_ID = os.environ["MONDAY_BOARD_ID"]
MONDAY_PHONE_COLUMN_ID = os.environ["MONDAY_PHONE_COLUMN_ID"]
MONDAY_REPLY_COLUMN_ID = os.environ["MONDAY_REPLY_COLUMN_ID"]
MONDAY_SEND_COLUMN_ID = os.environ["MONDAY_SEND_COLUMN_ID"]

app = FastAPI()


async def monday_request(query: str, variables: dict | None = None) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            MONDAY_API_URL,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(data["errors"])
        return data["data"]


async def find_item_by_phone(phone: str) -> str | None:
    query = """
    query ($boardId: ID!, $columnId: String!, $phone: String!) {
      items_page_by_column_values(
        board_id: $boardId
        columns: [{ column_id: $columnId, column_values: [$phone] }]
      ) {
        items { id }
      }
    }
    """
    data = await monday_request(
        query,
        {"boardId": MONDAY_BOARD_ID, "columnId": MONDAY_PHONE_COLUMN_ID, "phone": phone},
    )
    items = data["items_page_by_column_values"]["items"]
    return items[0]["id"] if items else None


async def create_contact_item(phone: str) -> str:
    query = """
    mutation ($boardId: ID!, $itemName: String!, $columnValues: JSON!) {
      create_item(board_id: $boardId, item_name: $itemName, column_values: $columnValues) { id }
    }
    """
    column_values = json.dumps({MONDAY_PHONE_COLUMN_ID: phone})
    data = await monday_request(
        query,
        {"boardId": MONDAY_BOARD_ID, "itemName": phone, "columnValues": column_values},
    )
    return data["create_item"]["id"]


async def post_update(item_id: str, body: str) -> None:
    query = """
    mutation ($itemId: ID!, $body: String!) {
      create_update(item_id: $itemId, body: $body) { id }
    }
    """
    await monday_request(query, {"itemId": item_id, "body": body})


async def get_item_columns(item_id: str) -> dict[str, str]:
    query = """
    query ($itemId: ID!) {
      items(ids: [$itemId]) {
        column_values { id text }
      }
    }
    """
    data = await monday_request(query, {"itemId": item_id})
    values = data["items"][0]["column_values"]
    return {c["id"]: c["text"] for c in values}


async def send_whatsapp_message(phone: str, text: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}",
            json={"number": phone, "text": text},
            headers={"apikey": EVOLUTION_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/evolution")
async def evolution_webhook(request: Request):
    payload = await request.json()
    print(f"[evolution webhook] payload recibido: {json.dumps(payload)[:2000]}")
    if payload.get("event") != "messages.upsert":
        return JSONResponse({"ignored": True})

    data = payload.get("data", {})
    key = data.get("key", {})
    if key.get("fromMe"):
        return JSONResponse({"ignored": True})

    phone = key.get("remoteJid", "").split("@")[0]
    message = data.get("message", {})
    text = message.get("conversation") or message.get("extendedTextMessage", {}).get("text", "")
    if not phone or not text:
        return JSONResponse({"ignored": True})

    item_id = await find_item_by_phone(phone)
    if item_id is None:
        item_id = await create_contact_item(phone)

    await post_update(item_id, f"\U0001F4E9 {text}")
    return JSONResponse({"ok": True})


@app.post("/webhook/monday")
async def monday_webhook(request: Request):
    payload = await request.json()
    print(f"[monday webhook] payload recibido: {json.dumps(payload)[:2000]}")

    # Monday verifica la URL del webhook con un "challenge" que hay que reenviar tal cual,
    # se recibe una sola vez al crear la suscripcion.
    if "challenge" in payload:
        return JSONResponse({"challenge": payload["challenge"]})

    event = payload.get("event", {})
    if event.get("columnId") != MONDAY_SEND_COLUMN_ID:
        return JSONResponse({"ignored": True})

    item_id = str(event["pulseId"])
    columns = await get_item_columns(item_id)
    phone = columns.get(MONDAY_PHONE_COLUMN_ID)
    reply_text = columns.get(MONDAY_REPLY_COLUMN_ID)
    if not phone or not reply_text:
        return JSONResponse({"ignored": True})

    await send_whatsapp_message(phone, reply_text)
    await post_update(item_id, f"✅ Enviado: {reply_text}")
    return JSONResponse({"ok": True})
