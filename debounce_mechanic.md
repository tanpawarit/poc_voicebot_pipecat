# Debounce Mechanism — VAD + Transcript Flow

เมื่อ user พูด ระบบจะได้รับ transcript หลายชิ้นติดกัน (เพราะ STT ส่งมาเป็น chunk)
Debounce ช่วยให้เรา **รอรวมทุก chunk ก่อน** แล้วค่อยส่งไป classify intent ทีเดียว

---

## ภาพรวม Pipeline

```
ไมโครโฟน
    │
    ▼
┌─────────────────────┐
│   VAD Processor      │  ← Silero VAD วิเคราะห์เสียง
│  (SileroVADAnalyzer) │    stop_secs = 0.4s (นิ่ง 0.4s = หยุดพูด)
└──────────┬──────────┘
           │ speech detected / stopped
           ▼
┌──────────────────────────────┐
│   STT (OpenAI gpt-4o-transcribe) │  ← แปลงเสียงเป็นข้อความ
└──────────┬───────────────────┘
           │ TranscriptionFrame("สวัสดีครับ")
           ▼
┌─────────────────────────────────────────────────────┐
│         CollectionRouterProcessor                    │
│              (Debounce Logic อยู่ที่นี่)              │
└─────────────────────────────────────────────────────┘
```

---

## Flow Debounce แบบละเอียด

```
TranscriptionFrame มาถึง
          │
          ▼
  debounce_secs <= 0?
     /         \
   YES           NO
    │             │
    ▼             ▼
Route ทันที    บันทึกลง buffer
(ไม่มี delay)  _pending_transcript_parts.append(text)
               _pending_transcript_stage = current_stage
                    │
                    ▼
            มี debounce task เก่าอยู่?
               /          \
             YES            NO
              │              │
              ▼              │
         Cancel task         │
         เก่าทิ้ง            │
              │              │
              └──────┬───────┘
                     │
                     ▼
           สร้าง debounce task ใหม่
           asyncio.sleep(1.0s)  ← รอ 1 วินาที
                     │
        ┌────────────┴────────────┐
        │  ระหว่างรอ 1 วินาที...  │
        │                         │
        │  chunk ใหม่มาอีก?        │
        │     ↓ YES               │
        │  append to buffer       │
        │  Cancel task เก่า       │
        │  สร้าง task ใหม่        │
        │  (reset timer)          │
        └────────────┬────────────┘
                     │ หมดเวลา (ไม่มี chunk ใหม่)
                     ▼
           _take_pending_transcript()
           ตรวจสอบ: stage ยังตรงกันไหม?
               /              \
            ไม่ตรง            ตรง
              │                │
              ▼                ▼
           ทิ้ง buffer    join(" ").join(parts)
           return ""      เช่น "ยังไงครับ? โทรมาเรื่องอะไร"
                               │
                               ▼
                    _route_transcript(combined_text)
                               │
                               ▼
                    Intent Classifier
                    (LLM/rule-based)
                               │
                               ▼
                    เปลี่ยน Stage / ตอบกลับ
```

---

## ตัวอย่างจริง — User พูดเป็น 2 ช่วง

```
เวลา (ms)  เหตุการณ์
──────────────────────────────────────────────────────────
  0ms      User พูด "ยังไงครับ?"
           → TranscriptionFrame #1 มาถึง
           → buffer = ["ยังไงครับ?"]
           → debounce timer เริ่ม (1000ms)

 400ms     VAD ตรวจพบ user พูดต่อ
           → TranscriptionFrame #2 "โทรมาเรื่องอะไร" มาถึง
           → CANCEL timer เดิม
           → buffer = ["ยังไงครับ?", "โทรมาเรื่องอะไร"]
           → debounce timer เริ่มใหม่ (1000ms)

1400ms     ไม่มีเสียงใหม่ → timer หมด
           → combined = "ยังไงครับ? โทรมาเรื่องอะไร"
           → ส่ง classifier ← classify ครั้งเดียว!

1450ms     classifier ตอบ: intent = FAQ
           → bot ตอบกลับ
```

---

## กรณีพิเศษ — Interrupt (bot กำลังพูด แต่ user พูดแทรก)

```
Bot กำลังพูด TTS อยู่
        │
        ▼
VAD ตรวจพบเสียง user
        │
        ▼
_clear_pending_transcript() ← ล้าง buffer ทันที
        │
        ▼
Cancel debounce task (ถ้ามี)
        │
        ▼
เริ่ม debounce ใหม่สำหรับ transcript ใหม่
```

---

## State Variables สำคัญ

| Variable | ประเภท | หน้าที่ |
|---|---|---|
| `_transcript_debounce_secs` | `float` | ความยาว delay (default: 1.0s) |
| `_pending_transcript_parts` | `list[str]` | buffer เก็บ chunk ทั้งหมด |
| `_pending_transcript_stage` | `CollectionStage` | stage ที่ buffer นี้เป็นของ |
| `_debounce_task` | `asyncio.Task` | task ที่กำลัง sleep อยู่ |
| `_debounce_lock` | `asyncio.Lock` | ป้องกัน race condition |

---

## Config

```bash
# .env
TRANSCRIPT_DEBOUNCE_SECS=1.0   # default 1 วินาที
VAD_STOP_SECS=0.4               # นิ่ง 0.4s ถือว่าหยุดพูด
TURN_END_TIMEOUT_SECS=2.0       # turn timeout สูงสุด
```

---

## สรุปง่าย ๆ

```
ไม่มี Debounce:
  chunk1 → classify → chunk2 → classify → chunk3 → classify
  (classify 3 ครั้ง, แพง, อาจได้ intent ผิด)

มี Debounce (1.0s):
  chunk1 → รอ... chunk2 → รอ... chunk3 → รอ 1s → รวม → classify
  (classify 1 ครั้ง, ถูก, ได้ context ครบ)
```
