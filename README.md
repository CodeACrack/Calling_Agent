# Your AI calling agent

This is an inbound phone agent for your Vobiz number **+91 8065354620**. It is designed for the path in your shared plan:

```text
Caller / Airtel conditional forwarding
              ↓
        Vobiz DID (after KYC)
              ↓
   this public HTTPS/WSS service
              ↓
        OpenAI Realtime voice agent
```

The agent identifies itself as AI, announces recording, speaks English/Hindi, captures callback details, refuses sensitive information, and hands off to a human when needed. It records the caller and agent in a stereo WAV file, then sends it to your WhatsApp number. It does not place automated outbound calls.

## Before it can receive a real call

1. Complete Vobiz KYC and confirm that the allocated trial number can receive inbound calls.
2. In Vobiz, enable an inbound SIP/media-stream or Voice API route for the number. A public phone number alone cannot stream audio to an application.
3. Deploy this service behind a public HTTPS/WSS domain, then set `PUBLIC_BASE_URL` in `.env`.
4. Add an OpenAI API key to `.env` (never paste it into chat or commit it).
5. Enter the service URL in Vobiz using its exact documented field. The route is `/vobiz/incoming`; media is `/vobiz/media`.
6. Create a WhatsApp Business Cloud API app, then put the access token, phone-number ID, and **your own WhatsApp number** in `.env`. The agent sends a text notification to that number after every call. Use a valid token generated for the same Meta business account and phone-number ID; short-lived test tokens expire and commonly cause `401 Unauthorized` responses.

For a production WhatsApp Business number, Meta may require an approved message template unless your number has an open 24-hour customer-service conversation with that WhatsApp business number. Use your account's test recipient while developing, then configure a template-based notification if Meta requires it.

Vobiz's carrier-specific webhook/media envelope is not included in the shared chat, so the two clearly marked adapter points in `app/main.py` may need a small adjustment once you can see Vobiz's SIP/Voice API documentation. The OpenAI side uses PCMU (G.711 mu-law), a common telephony format.

## Local setup

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Confirm the service with `http://localhost:8000/health`. For live carrier traffic, use a production host with HTTPS/WSS and keep `VOBIZ_WEBHOOK_SECRET` set if Vobiz can send a custom header.

## Deploy with Render using Docker

1. Push this project to a private GitHub repository. Do not commit `.env`, API keys, `.venv`, logs, or recordings.
2. In Render, choose **New > Web Service**, connect the repository, and select **Docker** as the runtime.
3. Leave the Dockerfile path as `./Dockerfile`. Render supplies the `PORT` environment variable used by the container.
4. Add the variables from `.env` in Render's Environment settings. Set `PUBLIC_BASE_URL` to `https://calling-agent.onrender.com`.
5. After deployment, verify `https://calling-agent.onrender.com/health`.

Configure Vobiz with this webhook URL:

```text
https://calling-agent.onrender.com/vobiz/incoming
```

The media-stream URL returned by the webhook is:

```text
wss://calling-agent.onrender.com/vobiz/media
```

Render must run this as a Web Service, not a Static Site or Background Worker, because Vobiz needs HTTPS and WebSocket access.

## Customize it

- Change business identity and voice in `.env`.
- Edit `app/agent.py` to add your business facts, hours, services, and escalation rules.
- The WAV files are retained locally in `data/recordings/`; plan a retention/deletion policy before using this in production.
- Do not add payment collection, OTP handling, or unconsented call recording. The agent announces recording, but you must also meet all applicable consent and telecom requirements.

## What is intentionally not automated

KYC submission, buying/recharging numbers, enabling carrier services, connecting your Airtel conditional forwarding, and any account login remain yours to do. They involve regulated telecom account and payment actions.
