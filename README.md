# poc_voicebot_pipecat

POC voicebot สำหรับงานโทรติดตามหนี้ภาษาไทย โดยใช้ `Pipecat` + `FastAPI` + `Gemini Live` และรันผ่าน `SmallWebRTC`.

ตอนนี้ใน repo มี flow ที่พร้อมใช้งานจริง 1 ตัวคือ `collection` และมี UI ทดสอบแบบ browser อยู่ที่หน้า root ของ server

## สิ่งที่โปรเจกต์นี้ทำ

- เปิด server ด้วย FastAPI
- รับ WebRTC offer จากหน้าเว็บ
- สร้าง Pipecat pipeline สำหรับเสียงเข้า/ออก
- ใช้ `GeminiLiveLLMService` เป็น voice model
- ใช้ `pipecat-flows` คุมบทสนทนา debt collection
- inject mock CRM data เข้า flow ก่อนเริ่มคุย

ไฟล์สำคัญ:

- `app_s2s/server.py` จุดเริ่มต้นของ S2S server
- `app_s2s/bot.py` ประกอบ Pipecat pipeline และเริ่ม flow
- `common/flows/collection.py` script บทสนทนา collection
- `common/flows/mock_crm.py` ข้อมูลลูกค้าจำลอง
- `common/config.py` อ่านค่าจาก environment

## Requirements

- Python 3.12
- `uv`
- Google API key สำหรับ Gemini Live
- Browser ที่เปิดไมค์ได้

## Setup

1. สร้างไฟล์ environment

```bash
cp .env.example .env
```

2. ใส่ค่า `GOOGLE_API_KEY` ใน `.env`

ตัวอย่างค่าที่รองรับตอนนี้:

```env
GOOGLE_API_KEY="your-google-api-key"
FLOW="collection"
HOST="0.0.0.0"
S2S_PORT="7861"
```

3. ติดตั้ง dependency

```bash
uv sync
```

## Run แบบ local

รัน server:

```bash
uv run python -m app_s2s
```

จากนั้นเปิด:

```text
https://localhost:7861/
```

สิ่งที่ควรรู้:

- server ถูกตั้งให้รันผ่าน TLS โดยใช้ไฟล์ใน `certs/`
- browser อาจเตือนเรื่อง self-signed certificate ในครั้งแรก
- เมื่อหน้าเว็บเปิดได้แล้ว กด `Connect` และอนุญาตการใช้ไมโครโฟน

เช็ก health endpoint:

```text
https://localhost:7861/api/health
```

## Run ด้วย Docker

```bash
docker compose up --build s2s
```

แล้วเปิด `https://localhost:7861/`

หมายเหตุ:

- ตอนนี้ `docker-compose.yml` รองรับ service `s2s` ตัวเดียว
- flow default ถูกตั้งเป็น `collection`

## Flow ปัจจุบัน

`collection` flow จะเดินประมาณนี้:

`opening -> verify -> overdue -> ptp/convince -> thank_you/refused -> end`

และมี branch สำหรับ:

- ลูกค้าไม่ว่าง
- คนอื่นรับสาย
- voicemail
- fallback กรณีคุยไม่สำเร็จ

mock CRM ที่ใช้ format prompt ถูกเก็บไว้ใน `common/flows/mock_crm.py`

## Troubleshooting

`Missing required environment variable: GOOGLE_API_KEY`

- ตรวจว่าไฟล์ `.env` มีค่า `GOOGLE_API_KEY`

`ModuleNotFoundError`

- รัน `uv sync` ใหม่หลัง clone repo

หน้าเว็บเปิดได้แต่คุยไม่ได้

- เช็กว่า browser อนุญาตไมค์แล้ว
- เช็กว่าเปิดผ่าน `https://localhost:7861/`
- เช็ก log ใน terminal ว่ามี error จาก Gemini หรือ WebRTC หรือไม่

## สถานะของ repo ตอนนี้

- มี implementation ของ `app_s2s` พร้อมใช้งาน
- มี `collection` flow อยู่จริงใน repo
- ไม่มี `app_cascaded` ในชุดโค้ดนี้

ถ้าจะเพิ่ม flow อื่น ให้เพิ่มไฟล์ flow ใหม่ใน `common/flows/` แล้วผูกเข้ากับ `common/flows/__init__.py`
