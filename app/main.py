"""Provider-neutral media bridge. Adapt `vobiz_media` once Vobiz media-stream details are enabled."""
import asyncio
import audioop
import base64
import json
import logging
import secrets
from contextlib import suppress
from pathlib import Path

from google import genai
from google.genai import types
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response

from .agent import instructions
from .config import get_settings
from .recording import CallRecorder

RECORDINGS_DIR = Path("data/recordings")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("calling-agent")
app = FastAPI(title="Vobiz AI Calling Agent", version="0.1.0")


@app.get("/health")
def health():
    settings = get_settings()
    return {"status": "ok", "live_calls_ready": bool(settings.gemini_api_key)}


@app.get("/recordings/{filename}")
def recording(filename: str):
    path = (RECORDINGS_DIR / Path(filename).name).resolve()
    recordings_root = RECORDINGS_DIR.resolve()
    if path.parent != recordings_root or not path.is_file():
        raise HTTPException(status_code=404, detail="Recording not found")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.api_route("/vobiz/hangup", methods=["GET", "POST"])
async def hangup_callback(request: Request):
    """Acknowledge Vobiz call-end callbacks without starting another call flow."""
    event = dict(request.query_params)
    if request.method == "POST":
        event.update(dict(await request.form()))
    log.info("Vobiz call ended: %s", event.get("CallUUID") or event.get("call_id") or "unknown")
    return Response(content="OK", media_type="text/plain")


@app.api_route("/vobiz/fallback", methods=["GET", "POST"])
async def fallback_callback():
    """Return a simple fallback response when Vobiz cannot execute the application."""
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Speak>We are unable to connect your call right now. Please try again later.</Speak>
  <Hangup/>
</Response>'''
    return Response(content=xml, media_type="application/xml")


@app.api_route("/vobiz/incoming", methods=["GET", "POST"])
async def incoming_call(request: Request, x_vobiz_secret: str | None = Header(default=None)):
    """Return VobizXML that starts the bidirectional media stream."""
    settings = get_settings()
    if settings.vobiz_webhook_secret and not secrets.compare_digest(
        x_vobiz_secret or "", settings.vobiz_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid Vobiz webhook secret")

    event = dict(request.query_params)
    form = await request.form()
    event.update(dict(form))
    if not event:
        try:
            event = await request.json()
        except Exception:
            event = {}
    call_id = event.get("CallUUID") or event.get("call_id") or event.get("uuid") or "unknown"
    log.info("Inbound call notification: %s", call_id)
    websocket_base_url = settings.public_base_url.rstrip("/")
    if websocket_base_url.startswith("https://"):
        websocket_base_url = "wss://" + websocket_base_url.removeprefix("https://")
    elif websocket_base_url.startswith("http://"):
        websocket_base_url = "ws://" + websocket_base_url.removeprefix("http://")
    websocket_url = f"{websocket_base_url}/vobiz/media"
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">{websocket_url}</Stream>
</Response>'''
    return Response(content=xml, media_type="application/xml")


@app.websocket("/vobiz/media")
async def vobiz_media(vobiz: WebSocket):
    """Relay G.711 mu-law audio between a carrier media stream and OpenAI Realtime.

    Expected carrier messages: {"event":"media", "media":{"payload":"<base64 PCMU>"}}.
    If Vobiz uses another envelope, change only `carrier_to_openai` / `openai_to_carrier`.
    """
    await vobiz.accept()
    settings = get_settings()
    if not settings.gemini_api_key:
        await vobiz.send_json({"event": "error", "message": "GEMINI_API_KEY is not configured"})
        await vobiz.close(code=1011)
        return

    client = genai.Client(api_key=settings.gemini_api_key)
    call_id = "unknown"
    stream_id = "unknown"
    inbound_encoding = "audio/x-mulaw"
    inbound_sample_rate = 8000
    media_frames = 0
    response_audio_chunks = 0
    recorder: CallRecorder | None = None
    try:
        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=instructions(settings),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
        )
        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=live_config) as gemini:

            async def carrier_to_openai():
                nonlocal call_id, stream_id, inbound_encoding, inbound_sample_rate, media_frames, recorder
                async for raw in vobiz.iter_text():
                    message = json.loads(raw)
                    if message.get("event") == "start":
                        start = message.get("start", {})
                        call_id = str(start.get("callId") or start.get("call_id") or message.get("call_id") or "unknown")
                        stream_id = str(start.get("streamId") or message.get("streamId") or "unknown")
                        media_format = start.get("mediaFormat", {})
                        inbound_encoding = str(media_format.get("encoding") or media_format.get("contentType") or inbound_encoding)
                        inbound_sample_rate = int(media_format.get("sampleRate") or 8000)
                        log.info("Vobiz stream started: call=%s stream=%s format=%s/%s", call_id, stream_id, inbound_encoding, inbound_sample_rate)
                        recorder = CallRecorder(call_id)
                        await gemini.send_realtime_input(
                            text="Say only the required first-turn greeting from your instructions, then stop speaking and wait for the caller."
                        )
                    if message.get("event") == "media":
                        payload = message.get("media", {}).get("payload")
                        if payload:
                            media_frames += 1
                            if recorder:
                                recorder.write_encoded(payload, "caller", inbound_encoding, inbound_sample_rate)
                            encoded = base64.b64decode(payload)
                            if "alaw" in inbound_encoding.lower():
                                pcm = audioop.alaw2lin(encoded, 2)
                            else:
                                pcm = audioop.ulaw2lin(encoded, 2)
                            pcm_16k, _ = audioop.ratecv(pcm, 2, 1, inbound_sample_rate, 16000, None)
                            await gemini.send_realtime_input(
                                audio=types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000")
                            )

            async def gemini_to_carrier():
                nonlocal response_audio_chunks
                async for response in gemini.receive():
                    server_content = response.server_content
                    if not server_content or not server_content.model_turn:
                        continue
                    for part in server_content.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            response_audio_chunks += 1
                            pcm_24k = part.inline_data.data
                            pcm_8k, _ = audioop.ratecv(pcm_24k, 2, 1, 24000, 8000, None)
                            audio_payload = base64.b64encode(audioop.lin2ulaw(pcm_8k, 2)).decode()
                            if recorder:
                                recorder.write_pcmu(audio_payload, "assistant")
                            
                            await vobiz.send_json({
                                "event": "playAudio",
                                "streamId": stream_id,
                                "media": {
                                    "contentType": "audio/x-mulaw",
                                    "sampleRate": 8000,
                                    "payload": audio_payload,
                                },
                            })

            tasks = [asyncio.create_task(carrier_to_openai()), asyncio.create_task(gemini_to_carrier())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            log.info("Vobiz media ended: call=%s inbound_frames=%s outbound_audio_chunks=%s", call_id, media_frames, response_audio_chunks)
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
            log.info("Recording saved locally for call %s: %s", call_id, recording)
