from pathlib import Path

import httpx

from .config import Settings


async def send_recording(settings: Settings, recording: Path, call_id: str) -> bool:
    """Upload a recording to Meta and send it as a WhatsApp audio message."""
    if not all((settings.whatsapp_access_token, settings.whatsapp_phone_number_id, settings.whatsapp_recipient)):
        return False
    base = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=45) as client:
        with recording.open("rb") as handle:
            upload = await client.post(
                f"{base}/media",
                headers=headers,
                data={"messaging_product": "whatsapp", "type": "audio/wav"},
                files={"file": (recording.name, handle, "audio/wav")},
            )
        upload.raise_for_status()
        media_id = upload.json()["id"]
        message = await client.post(
            f"{base}/messages",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp",
                "to": settings.whatsapp_recipient.lstrip("+"),
                "type": "audio",
                "audio": {"id": media_id},
            },
        )
        message.raise_for_status()
    return True
