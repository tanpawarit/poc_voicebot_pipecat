# System Architecture — POC Voicebot (OpenAI Cascaded)

## Overview

ระบบนี้เป็น voicebot แบบ real-time สำหรับ POC debt collection ภาษาไทย โดยใช้ `Pipecat` เป็น pipeline runtime, `FastAPI` เป็น server, `SmallWebRTC` เป็น transport, และ OpenAI สำหรับ `STT + intent classification + TTS`

แนวคิดหลักของเวอร์ชันนี้คือ deterministic flow:

- bot เปิดบทสนทนาด้วยสคริปต์คงที่
- รับเสียงลูกค้าแบบ checkpoint-by-checkpoint
- แปลงเสียงเป็นข้อความ
- classify opening intent และ verify intent แยกกัน
- route ไปยังสคริปต์ตอบกลับที่ fix ไว้
- จบสาย

## High-Level Architecture

```text
Browser / SIP Client
  -> WebRTC
FastAPI /api/offer
  -> run_bot(connection)
Pipecat Pipeline
  -> transport.input()
  -> VADProcessor(Silero)
  -> OpenAISTTService
  -> CollectionRouterProcessor
  -> OpenAITTSService
  -> transport.output()
```

## Runtime Components

### 1. Transport

- `common/transport.py`
- ใช้ `SmallWebRTCTransport`
- รับเสียงจาก browser และส่งเสียง bot กลับไป

### 2. Server

- `app_s2s/server.py`
- `POST /api/offer` รับ SDP offer และสร้าง WebRTC session
- เรียก `app_s2s.bot.run_bot()` เป็น background task

### 3. Bot Runtime

- `app_s2s/bot.py`
- ใช้ `PipelineTask` + `PipelineRunner`
- เปิด session ด้วย mock CRM state จาก `common/flows/mock_crm.py`
- สร้าง flow definition จาก `common/flows/collection.py`
- ใช้ OpenAI classifier + router processor ในการ route transcript

### 4. Deterministic Flow Definition

- `common/flows/collection.py`
- มีสคริปต์สำหรับ:
  - `opening`
  - `opening_retry`
  - `verify`
  - `verify_retry`
  - `overdue`
  - `busy|other_person|voicemail|faq|fallback`

ไม่มี `FlowManager`, ไม่มี node transition, และไม่มี tool calling

### 5. Intent Classification

- `common/openai_intent_classifier.py`
- ใช้ `AsyncOpenAI.responses.parse(...)`
- structured output แยก 2 checkpoint:
  - opening intent: `target|busy|other_person|voicemail|faq|unknown`
  - verify intent: `confirmed|target_unavailable|third_party_speaking|faq|unknown`

### 6. Router Processor

- `common/processors/collection_router.py`
- เมื่อได้รับ `StartFrame`:
  - ส่ง opening script ผ่าน `TTSSpeakFrame`
- เมื่อได้รับ final `TranscriptionFrame`:
  - ถ้าอยู่ stage `opening` และ classify ได้ `target` จะส่ง verify prompt แล้วรอฟังต่อ
  - ถ้าอยู่ stage `verify` และ classify ได้ `confirmed` จะส่ง overdue handoff script
  - ถ้าเป็น branch อื่นจะส่ง scripted response และ `EndFrame`
- ถ้า transcript ว่าง:
  - retry ได้ 1 ครั้งต่อ stage
  - ถ้าเกิน limit จะ fallback และจบสาย
- ถ้า transcript ว่าง หรือ classifier/STT ล้มเหลว:
  - ใช้ fallback script
  - ส่ง `EndFrame`

## Collection POC Flow

```text
opening
  -> target        -> verify
  -> busy          -> callback-close       -> end
  -> other_person  -> polite close         -> end
  -> voicemail     -> contact later        -> end
  -> faq           -> faq answer           -> end
  -> fallback      -> fallback close       -> end

verify
  -> confirmed             -> overdue handoff -> end
  -> target_unavailable    -> callback-close  -> end
  -> third_party_speaking  -> polite close    -> end
  -> faq                   -> faq answer      -> end
  -> fallback              -> fallback close  -> end
```

## Config

ค่าหลักอยู่ใน `common/config.py`

| Env Var | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | required | OpenAI auth |
| `OPENAI_BASE_URL` | empty | custom endpoint ถ้ามี |
| `OPENAI_STT_MODEL` | `gpt-4o-transcribe` | STT model |
| `OPENAI_INTENT_MODEL` | `gpt-4o-mini` | intent classifier |
| `OPENAI_TTS_MODEL` | `gpt-4o-mini-tts` | TTS model |
| `OPENAI_TTS_VOICE` | `sage` | TTS voice |
| `OPENAI_TTS_SPEED` | `0.94` | speaking rate |
| `OPENAI_TTS_INSTRUCTIONS` | natural Thai preset | speaking style instructions |
| `FLOW` | `collection` | active flow |
| `S2S_PORT` | `7861` | HTTPS port |
| `VAD_STOP_SECS` | `0.2` | silence threshold |
| `TURN_END_TIMEOUT_SECS` | `2.0` | observer timeout |

## Notes

- STT ใช้ `OpenAISTTService` แบบ cascaded ไม่ใช่ realtime omni session
- TTS ใช้ `OpenAITTSService` แยกต่างหาก
- voice และ speaking style เป็น configurable ผ่าน env เพื่อปรับความเป็นธรรมชาติของภาษาไทยได้ง่ายขึ้น
- repo นี้ตั้งใจเป็น happy-case POC ที่เรียบง่าย ไม่ครอบคลุม collection workflow เต็มรูปแบบ
