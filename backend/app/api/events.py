"""Server-Sent Events: realtime dashboard feed (status/incident/diagnosis/restart/recovery)."""
import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.utils.events import bus

router = APIRouter(tags=["events"])


@router.get("/api/events/stream")
async def stream():
    queue = bus.subscribe()

    async def gen():
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
