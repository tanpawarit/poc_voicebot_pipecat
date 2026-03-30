# TTS Cache Mechanism

ระบบ cache เสียง TTS เพื่อ **ไม่ต้องเรียก OpenAI API ซ้ำ** สำหรับประโยคเดิม
ลด latency และประหยัด cost สำหรับประโยคที่พูดบ่อย เช่น "ขอบคุณครับ", "รอสักครู่นะครับ"

---

## ภาพรวม

```
Bot ต้องการพูด "ขอบคุณครับ"
          │
          ▼
┌────────────────────────┐
│  CachedOpenAITTS       │
│  .run_tts("ขอบคุณครับ") │
└──────────┬─────────────┘
           │
           ▼
    สร้าง cache key
    (SHA256 hash)
           │
     ┌─────┴──────┐
     │            │
   HIT           MISS
     │            │
     ▼            ▼
เล่นเสียง    เรียก OpenAI API
จาก cache    → รับเสียงกลับมา
             → เก็บลง cache
             → เล่นเสียง
```

---

## Cache Key — สร้างยังไง?

key คือ SHA256 ของข้อมูลทั้งหมดที่ส่งผล TTS

```
input:
  {
    "model":        "gpt-4o-mini-tts",
    "voice":        "alloy",
    "speed":        1.0,
    "instructions": "พูดเป็นภาษาไทย",
    "sample_rate":  16000,
    "text":         "ขอบคุณครับ"
  }
        │
        ▼ json.dumps(sort_keys=True) → encode UTF-8
        │
        ▼ hashlib.sha256(...)
        │
        ▼
  "a3f9e2b1c4d..."  ← cache key (64 chars)
```

ถ้า text เดิม แต่เปลี่ยน voice หรือ speed = **key ต่างกัน = cache แยก**

---

## Flow แบบละเอียด

```
run_tts(text) ถูกเรียก
       │
       ▼
preprocess_for_tts(text)
(แปลงตัวเลข/คำย่อให้ TTS ออกเสียงถูก)
       │
       ▼
text อยู่ใน excluded_texts?
  เช่น "" หรือ whitespace-only
       │ YES → เรียก API ตรงๆ ไม่ cache
       │ NO
       ▼
สร้าง cache_key = SHA256(model+voice+speed+text+...)
       │
       ▼
cache.get(cache_key)
       │
   ┌───┴────────────────────┐
   │ HIT                    │ MISS
   ▼                        ▼
yield TTSAudioRawFrame   เรียก OpenAI TTS API
จาก cached.audio         (ส่ง request, รับ audio stream)
                              │
                              ▼
                         รวบรวม audio_chunks[]
                         (รับทีละ chunk, yield ไปเรื่อยๆ)
                              │
                              ▼
                         มี error?
                          YES → ไม่ cache, จบ
                          NO
                              │
                              ▼
                         cache.set(key,
                           audio = b"".join(chunks),
                           sample_rate = 16000,
                           num_channels = 1
                         )
                              │
                              ▼
                         เก็บลง OrderedDict ✓
```

---

## LRU Eviction — จัดการเมื่อ cache เต็ม

LRU = Least Recently Used → ลบของที่ไม่ได้ใช้นานสุดก่อน

```
cache มี 3 entries (max_entries=3):

  OrderedDict (เรียงตาม access ล่าสุด):
  ┌──────────┬────────────┐
  │ "a3f9..." │ 45 KB      │  ← เก่าสุด (ไม่ได้ใช้นาน)
  ├──────────┼────────────┤
  │ "b7c2..." │ 32 KB      │
  ├──────────┼────────────┤
  │ "e1d4..." │ 28 KB      │  ← ใหม่สุด (เพิ่งใช้)
  └──────────┴────────────┘

เพิ่ม entry ใหม่ "f5a1..." เข้ามา:
  → len > max_entries (3)
  → ลบ "a3f9..." (เก่าสุด, last=False)
  → _current_bytes -= 45KB

  ผลลัพธ์:
  ┌──────────┬────────────┐
  │ "b7c2..." │ 32 KB      │
  ├──────────┼────────────┤
  │ "e1d4..." │ 28 KB      │
  ├──────────┼────────────┤
  │ "f5a1..." │ 55 KB      │  ← ใหม่สุด
  └──────────┴────────────┘
```

**เงื่อนไข evict:**
- `len(entries) > max_entries` (128)
- `current_bytes > max_bytes` (64 MB)
- ลบวนจนเข้าเงื่อนไขทั้งคู่

---

## Cache.get() — อัปเดต LRU Position

```
cache.get("b7c2...")

ก่อน:
  [a3f9] → [b7c2] → [e1d4]  (เรียงเก่า→ใหม่)

หลัง get("b7c2"):
  → สร้าง entry ใหม่ (last_accessed = now)
  → move_to_end("b7c2")

  [a3f9] → [e1d4] → [b7c2]  ← b7c2 ย้ายมาท้าย (ถือว่า "ใหม่สุด")
```

---

## Prewarm — อุ่น cache ก่อน bot เริ่มรับสาย

```
Bot startup
     │
     ▼
prewarm_texts([
  "สวัสดีครับ ผมชื่อ...",
  "ขอโทษนะครับ ขอเชิญรอสักครู่",
  "ขอบคุณมากครับ",
  ...
])
     │
     ▼
for each text:
  key = SHA256(text)
  cache.has(key)?
    YES → ข้าม (มีอยู่แล้ว)
    NO  → เรียก OpenAI TTS
         → เก็บ audio ลง cache
         → พร้อมสำหรับ first call!
     │
     ▼
Bot พร้อมรับสาย
(ประโยคที่ prewarm แล้ว จะตอบได้ทันที ไม่มี delay)
```

---

## Singleton Pattern — cache ใช้ร่วมกันทั้ง process

```python
# ทุก request ใช้ cache เดียวกัน (process-wide)

get_shared_tts_cache(
    max_entries=128,
    max_bytes=67_108_864  # 64 MB
)

  ครั้งแรก → สร้าง TTSMemoryCache ใหม่
  ครั้งต่อไป → return instance เดิม (ถ้า config เหมือนกัน)
```

```
Process memory:
┌──────────────────────────────────────┐
│  _shared_cache (singleton)           │
│  ┌────────────────────────────────┐  │
│  │ OrderedDict (LRU)              │  │
│  │  key1: PCM audio bytes (45KB)  │  │
│  │  key2: PCM audio bytes (32KB)  │  │
│  │  key3: PCM audio bytes (28KB)  │  │
│  │  ...                           │  │
│  └────────────────────────────────┘  │
│  current_bytes: 105KB / 64MB         │
│  entries: 3 / 128                    │
└──────────────────────────────────────┘
       ↑ shared โดย bot instance ทั้งหมด
```

---

## Config

```bash
# .env
TTS_CACHE_ENABLED=true
TTS_CACHE_MAX_ENTRIES=128    # จำนวน phrase สูงสุด
TTS_CACHE_MAX_BYTES=67108864 # ขนาด RAM สูงสุด (64 MB)
TTS_CACHE_PREWARM_ENABLED=true
```

---

## สรุปง่าย ๆ

```
ไม่มี Cache:
  "ขอบคุณครับ" → OpenAI API (300-500ms) → เสียง
  "ขอบคุณครับ" → OpenAI API (300-500ms) → เสียง   ← ซ้ำ, แพง
  "ขอบคุณครับ" → OpenAI API (300-500ms) → เสียง   ← ซ้ำ, แพง

มี Cache:
  "ขอบคุณครับ" → OpenAI API (300-500ms) → เสียง + เก็บ cache
  "ขอบคุณครับ" → cache HIT (< 1ms) → เสียง  ← เร็วมาก, ฟรี!
  "ขอบคุณครับ" → cache HIT (< 1ms) → เสียง  ← เร็วมาก, ฟรี!
```
