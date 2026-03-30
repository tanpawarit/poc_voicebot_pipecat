# poc_voicebot_pipecat

POC voicebot ภาษาไทยสำหรับงานโทรติดตามหนี้ โดยใช้ `Pipecat` + `FastAPI` + `OpenAI` + `SmallWebRTC`

ตอนนี้ runtime หลักของ repo เป็นแบบ scripted-state routing:

`transport.input -> VAD -> OpenAI STT -> OpenAI LLM routing -> scripted OpenAI TTS -> transport.output`

Flow ที่มีอยู่คือ `collection` แบบ 2-step deterministic POC:

- bot พูด opening ก่อน
- ฟังคำตอบลูกค้าใน stage `opening`
- ถ้าเป็น target จะถามต่อใน stage `verify`
- ถ้าไม่มีคำตอบที่ใช้ได้ในแต่ละ stage จะถามซ้ำได้ 1 ครั้งก่อน fallback
- route ไปยัง `busy`, `other_person`, `voicemail`, `faq`, `fallback`, หรือ `overdue`
- จบสายทันที

## ไฟล์สำคัญ

- `app_s2s/server.py` FastAPI + WebRTC offer endpoint
- `app_s2s/bot.py` Pipecat pipeline แบบ OpenAI cascaded runtime
- `common/flows/collection.py` static script definition สำหรับ collection POC
- `common/openai_intent_classifier.py` OpenAI stage routing สำหรับเลือก next step
- `common/processors/collection_router.py` state machine ที่ให้ LLM เลือก transition แล้วพูดตาม script ตรง
- `common/flows/mock_crm.py` mock CRM state สำหรับ format script

## Requirements

- Python 3.12
- `uv`
- OpenAI API key
- browser ที่เปิดไมค์ได้

## Setup

1. สร้างไฟล์ environment

```bash
cp .env.example .env
```

2. ใส่ค่า `OPENAI_API_KEY` ใน `.env`

ตัวอย่างค่าที่รองรับ:

```env
OPENAI_API_KEY="your-openai-api-key"
OPENAI_BASE_URL=""
OPENAI_STT_MODEL="gpt-4o-transcribe"
OPENAI_STT_PROMPT="Transcribe Thai phone-call speech accurately. Preserve spoken particles such as ครับ ค่ะ นะคะ and proper names exactly as spoken. Do not summarize or add words that were not spoken."
OPENAI_INTENT_MODEL="gpt-4o-mini"
OPENAI_TTS_MODEL="gpt-4o-mini-tts"
OPENAI_TTS_VOICE="sage"
OPENAI_TTS_SPEED="0.94"
OPENAI_TTS_INSTRUCTIONS="Speak in natural Thai with a warm, human customer-service tone. Use smooth pacing, gentle prosody, and short natural pauses. Avoid robotic cadence, flat delivery, and over-enunciation."
TTS_CACHE_ENABLED="true"
TTS_CACHE_MAX_ENTRIES="128"
TTS_CACHE_MAX_BYTES="67108864"
TTS_CACHE_PREWARM_ENABLED="true"
TRANSCRIPT_DEBOUNCE_SECS="0.8"
FLOW="collection"
HOST="0.0.0.0"
S2S_PORT="7861"
VAD_STOP_SECS="0.2"
TURN_END_TIMEOUT_SECS="2.0"
```

3. ติดตั้ง dependency

```bash
uv sync
```

## Run

```bash
uv run python -m app_s2s
```

จากนั้นเปิด:

```text
https://localhost:7861/
```

สิ่งที่ควรรู้:

- server ใช้ TLS จากไฟล์ใน `certs/`
- browser อาจเตือนเรื่อง self-signed certificate ในครั้งแรก
- opening script จะถูกพูดทันทีเมื่อ session เริ่ม
- หลังจากลูกค้าตอบ ระบบจะ route ตาม stage ปัจจุบัน (`opening` หรือ `verify`)
- ระบบจะ prewarm เสียงของ non-opening prompts แบบ background เพื่อช่วยลด TTS latency
- opening และ opening retry ถูกตั้งใจให้ bypass cache ในเวอร์ชันนี้
- ระบบจะ debounce transcript ช่วงสั้น ๆ ก่อน classify เพื่อรวมคำตอบที่พูดเป็นหลายท่อน
- ถ้า STT เพี้ยน ให้ลองปรับ `OPENAI_STT_PROMPT` ให้เหมาะกับบริบทภาษาไทยและคำเฉพาะในสายงาน
- ถ้าเสียงยังแข็งเกินไป ให้ลองปรับ `OPENAI_TTS_VOICE`, `OPENAI_TTS_SPEED`, และ `OPENAI_TTS_INSTRUCTIONS`

เช็ก health endpoint:

```text
https://localhost:7861/api/health
```

## Flow ปัจจุบัน

`collection` ในเวอร์ชันนี้ไม่ใช่ multi-node LLM flow แล้ว แต่เป็น deterministic routing แบบ checkpoint:

`opening -> verify -> overdue`

สคริปต์หลักในเวอร์ชันนี้:

- `opening` ขอเรียนสายลูกค้า
- `verify` ยืนยันข้อมูลเจ้าของรถ
- `overdue` เป็น scripted handoff หลังยืนยันตัวตนสำเร็จ
- `busy`, `other_person`, `voicemail`, `faq`, `fallback` เป็นทางออกของแต่ละ checkpoint

ถ้า STT หรือ intent classification ล้มเหลว ระบบจะใช้ fallback script และปิดสาย

## Troubleshooting

`Missing required environment variable: OPENAI_API_KEY`

- ตรวจว่าไฟล์ `.env` มีค่า `OPENAI_API_KEY`

หน้าเว็บเปิดได้แต่คุยไม่ได้

- เช็กว่า browser อนุญาตไมค์แล้ว
- เช็กว่าเปิดผ่าน `https://localhost:7861/`
- เช็ก log ใน terminal ว่ามี error จาก OpenAI หรือ WebRTC หรือไม่

## Tests

```bash
uv run python -m pytest -q -p no:cacheprovider
```
