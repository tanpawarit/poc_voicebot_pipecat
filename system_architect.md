# System Architecture — POC Voicebot (Gemini Live)

## Overview

ระบบนี้เป็น voicebot แบบ real-time สำหรับ POC debt collection ภาษาไทย โดยใช้ `Pipecat` เป็น pipeline runtime, `FastAPI` เป็น server, `SmallWebRTC` เป็น transport, และ `Gemini Live` สำหรับ native audio conversation

แนวคิดหลักของเวอร์ชันนี้คือ one-turn scripted flow:

- bot เปิดบทสนทนาด้วย opening script
- ฟังคำตอบลูกค้า 1 turn
- ให้ Gemini ตีความ intent ภายในจากเสียงตอบกลับ
- ถ้าเป็น `target` ให้พูด step `verify`
- ถ้าไม่ใช่ `target` ให้พูด scripted close ที่ตรงกับ branch
- จบสาย

## High-Level Architecture

```text
Browser / SIP Client
  -> WebRTC
FastAPI /api/offer
  -> run_bot(connection)
Pipecat Pipeline
  -> transport.input()
  -> GeminiContextBootstrapProcessor
  -> GeminiLiveLLMService
  -> EndCallAfterResponsesProcessor
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
- สร้าง Gemini system instruction จาก `common/flows/collection.py`
- seed initial kickoff message หนึ่งครั้งเพื่อให้ Gemini เปิดสายเอง
- ปิดสายหลัง `LLMFullResponseEndFrame` ครบ 2 ครั้ง: opening + scripted reply

### 4. Scripted Flow Definition

- `common/flows/collection.py`
- มีเพียง:
  - `opening`
  - `verify`
  - `responses[busy|other_person|voicemail]`
  - `fallback`
- script เดิมถูก compile เป็น system instruction เพื่อให้ Gemini Live ทำ flow เดิมแบบ native audio

## Collection POC Flow

```text
opening
  -> target        -> verify script        -> end
  -> busy          -> callback-close       -> end
  -> other_person  -> polite close         -> end
  -> voicemail     -> contact later        -> end
  -> fallback      -> callback-close       -> end
```

## Config

ค่าหลักอยู่ใน `common/config.py`

| Env Var | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | required | Gemini auth |
| `GOOGLE_API_KEY` | optional fallback | ใช้แทน `GEMINI_API_KEY` ได้ |
| `GEMINI_LIVE_MODEL` | `gemini-3.1-flash-live-preview` | Gemini Live model |
| `GEMINI_LIVE_VOICE` | `Aoede` | voice name |
| `FLOW` | `collection` | active flow |
| `S2S_PORT` | `7861` | HTTPS port |

## Notes

- ไม่มี local VAD, STT, หรือ TTS แยกใน runtime หลัก
- intent routing ยังเป็น deterministic ในเชิง business flow แต่ถูกอธิบายผ่าน Gemini system instruction เพียงเส้นทางเดียว
- repo นี้ตั้งใจเป็น happy-case POC ที่เรียบง่าย ไม่ครอบคลุม collection workflow เต็มรูปแบบ
