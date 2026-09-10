import httpx

from .config import Settings


async def send_call_message(settings: Settings, call_id: str) -> bool:
    """Send a text notification after a call recording is generated."""
    if not all((settings.whatsapp_access_token, settings.whatsapp_phone_number_id, settings.whatsapp_recipient)):
        return False
    base = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=45) as client:
        message = await client.post(
            f"{base}/messages",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp",
                "to": settings.whatsapp_recipient.lstrip("+"),
                "type": "text",
                "text": {"body": f"A recording was generated for call {call_id}."},
            },
        )
        message.raise_for_status()
    return True
