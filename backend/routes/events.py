import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.events.bus import event_bus

router = APIRouter(prefix="/events", tags=["Global Events"])

@router.get("/stream")
async def stream_events():
    """SSE endpoint for streaming global telemetry and checklist updates to the frontend."""
    async def event_generator():
        q = event_bus.subscribe("global")
        try:
            while True:
                data = await q.get()
                # Server-Sent Events must start with 'data: ' and end with '\n\n'
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            event_bus.unsubscribe("global", q)
            raise
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
