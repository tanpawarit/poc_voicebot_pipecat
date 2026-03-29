# poc_voicebot_pipecat

POC voicebot ภาษาไทยสำหรับงานโทรติดตามหนี้ โดยใช้ `Pipecat` + `FastAPI` + `Gemini Live` + `SmallWebRTC`

runtime หลักของ repo ตอนนี้เป็น Gemini Live ล้วนๆ:

`transport.input -> Gemini Live -> transport.output`

flow ปัจจุบันยังคงเป็น `collection` แบบ happy-case POC:

- bot พูด opening ทันที
- ฟังคำตอบลูกค้า 1 turn
- ตีความเป็น `target`, `busy`, `other_person`, หรือ `voicemail` ภายใน Gemini
- พูด scripted reply ตาม branch
- จบสายทันที

## ไฟล์สำคัญ

- `app_s2s/server.py` FastAPI + WebRTC offer endpoint
- `app_s2s/bot.py` Pipecat pipeline แบบ Gemini Live native audio
- `common/flows/collection.py` scripted collection flow และ Gemini system instruction builder
- `common/flows/mock_crm.py` mock CRM state สำหรับ format script
- `common/transport.py` SmallWebRTC transport

## Requirements

- Python 3.12
- `uv`
- Gemini API key
- browser ที่เปิดไมค์ได้

## Setup

1. สร้างไฟล์ environment

```bash
cp .env.example .env
```

2. ใส่ค่า `GEMINI_API_KEY` ใน `.env`

ตัวอย่างค่าที่รองรับ:

```env
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_LIVE_MODEL="gemini-3.1-flash-live-preview"
GEMINI_LIVE_VOICE="Aoede"
FLOW="collection"
HOST="0.0.0.0"
S2S_PORT="7861"
```

ถ้าคุณใช้ env เดิมของ Google อยู่แล้ว สามารถใช้ `GOOGLE_API_KEY` แทน `GEMINI_API_KEY` ได้

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
- หลังจากลูกค้าตอบ 1 turn ระบบจะตอบกลับตาม script และปิดสาย

เช็ก health endpoint:

```text
https://localhost:7861/api/health
```

## Flow ปัจจุบัน

`collection` ในเวอร์ชันนี้เป็น scripted Gemini Live runtime:

`opening -> infer target|busy|other_person|voicemail -> scripted reply -> end`

สคริปต์แต่ละ branch:

- `target` ยืนยันตัวตนด้วยทะเบียนรถ
- `busy` แจ้งว่าจะติดต่อใหม่ภายหลัง
- `other_person` ขอโทษและวางสาย
- `voicemail` ฝากข้อความสั้น ๆ ว่าจะติดต่อใหม่

ถ้า Gemini ไม่มั่นใจ intent ระบบจะใช้ fallback script เดียวกับ `busy`

## Troubleshooting

`Missing required environment variable: GEMINI_API_KEY or GOOGLE_API_KEY`

- ตรวจว่าไฟล์ `.env` มีค่า `GEMINI_API_KEY` หรือ `GOOGLE_API_KEY`

หน้าเว็บเปิดได้แต่คุยไม่ได้

- เช็กว่า browser อนุญาตไมค์แล้ว
- เช็กว่าเปิดผ่าน `https://localhost:7861/`
- เช็ก log ใน terminal ว่ามี error จาก Gemini Live หรือ WebRTC หรือไม่

## Tests

```bash
uv run python -m pytest -q -p no:cacheprovider
```
