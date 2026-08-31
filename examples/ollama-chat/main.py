"""Minimal ChatGPT-style app: FastAPI backend proxying chat requests to a local
Ollama server, plus a static frontend. Meant to run on a FoxyGPU-managed Colab GPU
where `ollama serve` is already running on localhost:11434.
"""

import json
import os

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")

app = FastAPI()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/api/chat")
async def chat(req: ChatRequest):
    async def stream():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": MODEL,
                    "messages": [m.model_dump() for m in req.messages],
                    "stream": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield json.dumps({"error": body.decode(errors="replace")}) + "\n"
                    return
                async for line in resp.aiter_lines():
                    if line:
                        yield line + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            return {"ollama": resp.status_code == 200, "model": MODEL}
    except httpx.HTTPError as e:
        return {"ollama": False, "error": str(e), "model": MODEL}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
