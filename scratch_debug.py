import asyncio
import sys

# On Windows, SelectorEventLoop does not use proactor socketpair fallback
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
resp = client.get("/health")
print("Response:", resp.json())
