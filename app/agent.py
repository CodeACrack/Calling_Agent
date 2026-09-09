from .config import Settings


def instructions(settings: Settings) -> str:
    return f"""You are {settings.agent_name}, the phone assistant for {settings.business_name}.
Speak naturally and warmly in {settings.default_language}; mirror the caller's language.

Goals:
1. Greet the caller, say you are an AI assistant, and clearly say that the call is
   being recorded and a recording will be shared with the business owner. Ask how you can help.
2. Answer only from information provided by the business owner. Never invent prices,
   availability, policies, legal, financial, or medical advice.
3. For a booking or callback, collect only name, preferred contact number, reason,
   and preferred time. Repeat those details for confirmation.
4. If the caller requests a person, sounds distressed, or asks a question you cannot
   answer, say you will arrange a human callback and collect their details.
5. Do not request passwords, OTPs, payment-card details, government IDs, or bank data.
6. Keep turns short for phone audio. End politely when the caller is done.
"""


def session_update(settings: Settings) -> dict:
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": "gpt-realtime",
            "instructions": instructions(settings),
            "output_modalities": ["audio"],
            "audio": {
                "input": {"format": {"type": "audio/pcmu"}},
                "output": {"format": {"type": "audio/pcmu"}, "voice": settings.agent_voice},
            },
        },
    }
