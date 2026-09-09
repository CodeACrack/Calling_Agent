"""Provider-neutral media bridge. Adapt `vobiz_media` once Vobiz media-stream details are enabled."""
import asyncio
import json
import logging
import secrets
from contextlib import suppress

import websockets
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .agent import session_update
from .config import get_settings
from .recording import CallRecorder
from .whatsapp import send_recording

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("calling-agent")
app = FastAPI(title="Vobiz AI Calling Agent", version="0.1.0")


@app.get("/health")
def health():
    settings = get_settings()
    return {"status": "ok", "live_calls_ready": bool(settings.openai_api_key)}


@app.post("/vobiz/incoming")
async def incoming_call(request: Request, x_vobiz_secret: str | None = Header(default=None)):
    """Inbound webhook endpoint. Configure this as Vobiz's call-answer URL when available."""
    settings = get_settings()
    if settings.vobiz_webhook_secret and not secrets.compare_digest(
        x_vobiz_secret or "", settings.vobiz_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid Vobiz webhook secret")

    event = await request.json()
    call_id = event.get("call_id") or event.get("uuid") or "unknown"
    log.info("Inbound call notification: %s", call_id)
    # Vobiz's exact answer schema must be inserted here after its media-stream feature
    # is enabled. This deliberately does not pretend that a generic JSON response will
    # control a real carrier call.
    return JSONResponse({
        "status": "received",
        "call_id": call_id,
        "media_websocket": f"{settings.public_base_url.rstrip('/')}/vobiz/media",
        "setup_required": "Map this value to Vobiz's documented media-stream/SIP answer field.",
    })


@app.websocket("/vobiz/media")
async def vobiz_media(vobiz: WebSocket):
    """Relay G.711 mu-law audio between a carrier media stream and OpenAI Realtime.

    Expected carrier messages: {"event":"media", "media":{"payload":"<base64 PCMU>"}}.
    If Vobiz uses another envelope, change only `carrier_to_openai` / `openai_to_carrier`.
    """
    await vobiz.accept()
    settings = get_settings()
    if not settings.openai_api_key:
        await vobiz.send_json({"event": "error", "message": "OPENAI_API_KEY is not configured"})
        await vobiz.close(code=1011)
        return

    realtime_url = "wss://api.openai.com/v1/realtime?model=gpt-realtime"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    call_id = "unknown"
    recorder: CallRecorder | None = None
    try:
        async with websockets.connect(realtime_url, additional_headers=headers) as openai:
            await openai.send(json.dumps(session_update(settings)))

            async def carrier_to_openai():
                nonlocal call_id, recorder
                async for raw in vobiz.iter_text():
                    message = json.loads(raw)
                    if message.get("event") == "start":
                        call_id = str(message.get("start", {}).get("call_id") or message.get("call_id") or "unknown")
                        recorder = CallRecorder(call_id)
                    if message.get("event") == "media":
                        payload = message.get("media", {}).get("payload")
                        if payload:
                            if recorder:
                                recorder.write_pcmu(payload, "caller")
                            await openai.send(json.dumps({
                                "type": "input_audio_buffer.append", "audio": payload
                            }))
                    elif message.get("event") in {"stop", "hangup"}:
                        break

            async def openai_to_carrier():
                async for raw in openai:
                    event = json.loads(raw)
                    if event.get("type") == "response.output_audio.delta":
                        if recorder:
                            recorder.write_pcmu(event["delta"], "assistant")
                        await vobiz.send_json({
                            "event": "media", "media": {"payload": event["delta"]}
                        })
                    elif event.get("type") == "error":
                        log.error("Realtime error: %s", event)

            tasks = [asyncio.create_task(carrier_to_openai()), asyncio.create_task(openai_to_carrier())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Call bridge failed")
        with suppress(Exception):
            await vobiz.send_json({"event": "error", "message": "Call bridge unavailable"})
        with suppress(Exception):
            await vobiz.close(code=1011)
    finally:
        if recorder:
            recording = recorder.close()
            try:
                delivered = await send_recording(settings, recording, call_id)
                log.info("Recording %s for call %s", "sent to WhatsApp" if delivered else "saved locally", call_id)
            except Exception:
                log.exception("Could not send recording to WhatsApp; saved locally: %s", recording)
