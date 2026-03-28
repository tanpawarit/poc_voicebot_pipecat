# System Architecture — POC Voicebot (Pipecat S2S)

## Overview

A real-time **Speech-to-Speech (S2S) voice bot** built on [Pipecat](https://github.com/pipecat-ai/pipecat) for automated debt-collection calls. The bot persona is **"Nong Jai"** (น้องใจ), an AI agent for Ngern Hai Jai Co., Ltd. (บริษัทเงินให้ใจจำกัด).

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser / SIP Client                                       │
│  (WebRTC audio in/out)                                      │
└────────────────────┬────────────────────────────────────────┘
                     │ WebRTC (DTLS-SRTP)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Server  (HTTPS / WSS, port 7861)                   │
│  POST /api/offer  →  SmallWebRTCConnection.initialize()     │
│  Background task →  run_bot(connection)                     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Pipecat Pipeline                                           │
│                                                             │
│  transport.input()                                          │
│       ↓  (raw audio frames)                                 │
│  LLMContextAggregator [user]                                │
│       ↓  VAD (SileroVAD, stop_secs=0.3)                    │
│       ↓  Turn detection (LocalSmartTurnAnalyzerV3)          │
│       ↓  MinWordsUserTurnStartStrategy (min_words=2)        │
│  GeminiLiveLLMService   ← Speech-to-Speech model           │
│       ↓  (audio response frames)                            │
│  LLMContextAggregator [assistant]                           │
│       ↓                                                     │
│  transport.output()                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### 1. Transport Layer — `common/transport.py`

| Property | Value |
|---|---|
| Protocol | WebRTC via `SmallWebRTCTransport` |
| ICE | Google STUN (`stun:stun.l.google.com:19302`) |
| TLS | Self-signed cert (`certs/cert.pem` / `key.pem`) |
| Audio | Bidirectional (`audio_in_enabled`, `audio_out_enabled`) |

### 2. Server — `app_s2s/server.py`

| Endpoint | Description |
|---|---|
| `GET /` | Serves HTML client page |
| `POST /api/offer` | Accepts WebRTC SDP offer, spawns bot as background task |
| `GET /api/health` | Health check |

Server is started with `uvicorn` over HTTPS on port **7861** (configurable via `S2S_PORT`).

### 3. Bot Pipeline — `app_s2s/bot.py`

- **LLM**: `GeminiLiveLLMService` — Google Gemini Live (S2S model), voice `"Kore"`, inference on context initialization enabled
- **VAD**: `SileroVADAnalyzer` with `stop_secs=0.3`
- **Turn detection**: `LocalSmartTurnAnalyzerV3` (local CPU model)
- **Turn start guard**: `MinWordsUserTurnStartStrategy(min_words=2)` — ignores utterances shorter than 2 words to avoid noise-triggered calls
- **Metrics**: `enable_metrics=True`, `enable_usage_metrics=True`
- **Turn observer**: `TurnTrackingObserver(turn_end_timeout_secs=2.0)` — logs turn count, duration, and interruption status

### 4. Configuration — `common/config.py`

| Env Var | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | _(required)_ | Gemini API key |
| `FLOW` | `collection` | Active flow name |
| `HOST` | `0.0.0.0` | Bind address |
| `S2S_PORT` | `7861` | Server port |
| `CASCADED_PORT` | `7860` | Reserved for cascaded mode |

### 5. Flow Engine — `common/flows/`

Uses [pipecat-flows](https://github.com/pipecat-ai/pipecat-flows) for structured conversation management.

**FlowManager** orchestrates node transitions by:
1. Injecting CRM state into `flow_manager.state` before initialization
2. Calling `flow_manager.initialize(initial_node)` to start the first node
3. Each node defines a **system prompt** + **function schemas** that the LLM calls to signal state transitions

---

## Collection Flow State Machine

Entry point: `create_initial_node()` → `create_opening_node()`

```
opening ──── target ────► verify ──── confirmed ────► overdue
         │                        └── not confirmed ─► fallback
         ├── busy ────────────────────────────────────► end
         ├── other_person ────────────────────────────► end
         └── voicemail ───────────────────────────────► end

overdue ──── already_paid ───────────────────────────► paid ──► end
         ├── agree_to_pay ──────────────────────────► ptp
         └── refuse ────────────────────────────────► convince

convince ─── agreed ──────────────────────────────► ptp
          └── refused ──────────────────────────────► refused ──► end

ptp ──────────────────────────────────────────────► thank_you ──► end

any node (no response × 2) ──────────────────────► fallback ──► end
any node (voicemail detected) ───────────────────► voicemail ──► end
```

### Node Summary

| Node | Purpose | Function Called |
|---|---|---|
| `opening` | Greet and identify who answered | `opening_response` |
| `verify` | Confirm customer identity via plate number | `verify_response` |
| `overdue` | Inquire about overdue payment status | `overdue_response` |
| `ptp` | Secure a Promise-to-Pay (date + amount) | `ptp_response` |
| `convince` | Persuade customer who initially refused | `convince_response` |
| `busy` | Record preferred callback time | `busy_response` |
| `other_person` | Leave message with third party (no debt disclosure) | `other_person_response` |
| `paid` | Acknowledge already-paid customer | `wrap_up` |
| `thank_you` | Close after successful PTP | `wrap_up` |
| `refused` | Close politely after final refusal | `wrap_up` |
| `voicemail` | Leave brief message on answering machine | `wrap_up` |
| `fallback` | Handle repeated no-response | `wrap_up` |
| `end` | Terminate session (`post_actions: end_conversation`) | — |

---

## CRM Integration — `common/flows/mock_crm.py`

State injected into `flow_manager.state` before flow initialization:

| Field | Example | Description |
|---|---|---|
| `customer_name` | `สมชาย ใจดี` | Full name |
| `first_name` | `สมชาย` | First name (for verify node) |
| `phone` | `0812345678` | Phone number |
| `lic_no` | `กข 1234` | Vehicle plate |
| `province` | `กรุงเทพมหานคร` | Plate province |
| `due_date` | `5 มีนาคม 2568` | Overdue billing date |
| `due_amount` | `8,500` | Amount owed (THB) |
| `ptp_date` | `31 มีนาคม 2568` | Default PTP date to propose |
| `deadline` | `2 เมษายน 2568` | Final deadline before legal action |
| `contract_no` | `CHJ-2024-001234` | Contract reference |
| `oa_code` | `A888` | OA agent code |
| `call_attempt` | `1` | Call attempt number |

> **Production note**: Replace `MOCK_CUSTOMER` with a CRM API call keyed by inbound phone number or session metadata.

---

## Result Codes

Set in `flow_manager.state["result_code"]` at session end:

| Code | Meaning |
|---|---|
| `PTP` | Customer committed to a payment date |
| `REFUSE` | Customer refused after persuasion |
| `MSG` | Message left (busy / third party) |
| `REACHED` | Customer reached, conversation completed normally |

---

## Latency Profile

Since this project uses **Gemini Live (S2S)**, the STT and TTS layers are eliminated. The effective latency stack is:

```
User speaks
  → VAD silence detection  (~300ms, stop_secs=0.3)
  → SmartTurn analysis      (~local CPU, <50ms)
  → Gemini Live round-trip  (~300–600ms TTFB)
  → Audio playback starts
```

**Estimated TTFB**: ~600ms–900ms under normal network conditions.

### Tunable parameters

| Parameter | Current | Effect of lowering |
|---|---|---|
| `stop_secs` | `0.3` | Faster response, higher false-cut risk |
| `min_words` | `2` | Allows single-word triggers |
| `turn_end_timeout_secs` | `2.0` | Shorter post-turn buffer |

---

## File Tree

```
poc_voicebot_pipecat/
├── app_s2s/
│   ├── __main__.py          # Entry point
│   ├── server.py            # FastAPI + uvicorn
│   └── bot.py               # Pipeline + FlowManager
├── common/
│   ├── config.py            # Settings (env vars)
│   ├── transport.py         # SmallWebRTC factory
│   ├── logging.py           # Logging setup
│   ├── html.py              # Client HTML page
│   ├── session.py           # Session utilities
│   └── flows/
│       ├── __init__.py      # Flow registry (get_flow)
│       ├── collection.py    # Debt-collection flow
│       └── mock_crm.py      # Mock CRM data
├── certs/                   # TLS certificates
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## Deployment

```bash
# Local
uv run python -m app_s2s

# Docker
docker compose up
```

Requires:
- `GOOGLE_API_KEY` in `.env`
- TLS certs in `certs/` (WebRTC requires HTTPS)
