"""
Thai phonetic expansion for TTS — license plates, provinces, etc.

Usage:
    from common.thai_phonetics import preprocess_for_tts

    preprocess_for_tts("ทะเบียนรถ กท 1234 จังหวัด กทม")
    # → "ทะเบียนรถ กอ ไก่ ทอ ทหาร หนึ่ง สอง สาม สี่ จังหวัด กรุงเทพมหานคร"
"""

import re

# ---------------------------------------------------------------------------
# Thai consonant phonetic names (ชื่อพยัญชนะ)
# ---------------------------------------------------------------------------
THAI_CONSONANT_NAMES: dict[str, str] = {
    "ก": "กอ ไก่",
    "ข": "ขอ ไข่",
    "ฃ": "ขอ ขวด",
    "ค": "คอ ควาย",
    "ฅ": "คอ คน",
    "ฆ": "คอ ระฆัง",
    "ง": "งอ งู",
    "จ": "จอ จาน",
    "ฉ": "ฉอ ฉิ่ง",
    "ช": "ชอ ช้าง",
    "ซ": "ซอ โซ่",
    "ฌ": "ชอ เชอ",
    "ญ": "ยอ หญิง",
    "ฎ": "ดอ ชฎา",
    "ฏ": "ตอ ปฏัก",
    "ฐ": "ถอ ฐาน",
    "ฑ": "ทอ มณโฑ",
    "ฒ": "ทอ ผู้เฒ่า",
    "ณ": "นอ เณร",
    "ด": "ดอ เด็ก",
    "ต": "ตอ เต่า",
    "ถ": "ถอ ถุง",
    "ท": "ทอ ทหาร",
    "ธ": "ทอ ธง",
    "น": "นอ หนู",
    "บ": "บอ ใบไม้",
    "ป": "ปอ ปลา",
    "ผ": "ผอ ผึ้ง",
    "ฝ": "ฝอ ฝา",
    "พ": "พอ พาน",
    "ฟ": "ฟอ ฟัน",
    "ภ": "พอ สำเภา",
    "ม": "มอ ม้า",
    "ย": "ยอ ยักษ์",
    "ร": "รอ เรือ",
    "ล": "ลอ ลิง",
    "ว": "วอ แหวน",
    "ศ": "สอ ศาลา",
    "ษ": "สอ ฤๅษี",
    "ส": "สอ เสือ",
    "ห": "หอ หีบ",
    "ฬ": "ลอ จุฬา",
    "อ": "ออ อ่าง",
    "ฮ": "ฮอ นกฮูก",
}

# Thai consonant character class for regex
_THAI_CONSONANTS = "".join(THAI_CONSONANT_NAMES.keys())

# ---------------------------------------------------------------------------
# Thai digit names (อ่านทีละหลัก สำหรับทะเบียนรถ)
# ---------------------------------------------------------------------------
THAI_DIGIT_NAMES: dict[str, str] = {
    "0": "ศูนย์",
    "1": "หนึ่ง",
    "2": "สอง",
    "3": "สาม",
    "4": "สี่",
    "5": "ห้า",
    "6": "หก",
    "7": "เจ็ด",
    "8": "แปด",
    "9": "เก้า",
}

# ---------------------------------------------------------------------------
# Province code → full name
# (รหัสย่อจังหวัดที่ใช้ในทะเบียนรถและทั่วไป)
# ---------------------------------------------------------------------------
PROVINCE_NAMES: dict[str, str] = {
    "กทม": "กรุงเทพมหานคร",
    "กท": "กรุงเทพมหานคร",
    "กบ": "กระบี่",
    "กจ": "กาญจนบุรี",
    "กส": "กาฬสินธุ์",
    "กพ": "กำแพงเพชร",
    "ขก": "ขอนแก่น",
    "จบ": "จันทบุรี",
    "ฉช": "ฉะเชิงเทรา",
    "ชบ": "ชลบุรี",
    "ชย": "ชัยภูมิ",
    "ชน": "ชัยนาท",
    "ชพ": "ชุมพร",
    "ชร": "เชียงราย",
    "ชม": "เชียงใหม่",
    "ตร": "ตรัง",
    "ตก": "ตาก",
    "นค": "นครนายก",
    "นฐ": "นครปฐม",
    "นพ": "นครพนม",
    "นม": "นครราชสีมา",
    "นศ": "นครศรีธรรมราช",
    "นว": "นครสวรรค์",
    "นบ": "นนทบุรี",
    "นย": "นราธิวาส",
    "นน": "น่าน",
    "บง": "บึงกาฬ",
    "บร": "บุรีรัมย์",
    "ปท": "ปทุมธานี",
    "ปน": "ปัตตานี",
    "พย": "พระนครศรีอยุธยา",
    "พล": "พะเยา",
    "พง": "พังงา",
    "พท": "พัทลุง",
    "พจ": "พิจิตร",
    "พษ": "พิษณุโลก",
    "พบ": "เพชรบุรี",
    "พร": "เพชรบูรณ์",
    "แพ": "แพร่",
    "พม": "พะเยา",
    "ภก": "ภูเก็ต",
    "มห": "มหาสารคาม",
    "มก": "มุกดาหาร",
    "มส": "แม่ฮ่องสอน",
    "ยส": "ยโสธร",
    "ยล": "ยะลา",
    "รอ": "ร้อยเอ็ด",
    "รน": "ระนอง",
    "รย": "ระยอง",
    "รบ": "ราชบุรี",
    "ลป": "ลำปาง",
    "ลพ": "ลำพูน",
    "ลย": "เลย",
    "ลก": "ลำปาง",
    "สก": "สกลนคร",
    "สข": "สงขลา",
    "สต": "สตูล",
    "สบ": "สมุทรปราการ",
    "สส": "สมุทรสงคราม",
    "สค": "สมุทรสาคร",
    "สห": "สระแก้ว",
    "สบ": "สระบุรี",
    "สน": "สิงห์บุรี",
    "สก": "สุโขทัย",
    "สพ": "สุพรรณบุรี",
    "สฎ": "สุราษฎร์ธานี",
    "สน": "สุรินทร์",
    "หน": "หนองคาย",
    "หบ": "หนองบัวลำภู",
    "อง": "อ่างทอง",
    "อด": "อุดรธานี",
    "อบ": "อุบลราชธานี",
    "อน": "อุตรดิตถ์",
    "อท": "อุทัยธานี",
    "อน": "อำนาจเจริญ",
}

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Thai license plate: 1-3 consonants + optional space + 1-4 digits
# e.g. "กท 1234", "กข1234", "กขค 99"
_PLATE_RE = re.compile(
    rf"([{_THAI_CONSONANTS}]{{1,3}})\s*(\d{{1,4}})"
)

# Province code standalone (word boundary via surrounding non-Thai context)
_PROVINCE_RE = re.compile(
    r"(?<!\S)(" + "|".join(sorted(PROVINCE_NAMES.keys(), key=len, reverse=True)) + r")(?!\S)"
)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _spell_consonants(text: str) -> str:
    """Spell out each Thai consonant using its phonetic name."""
    return " ".join(THAI_CONSONANT_NAMES[c] for c in text if c in THAI_CONSONANT_NAMES)


def _spell_digits(text: str) -> str:
    """Read each digit individually in Thai."""
    return " ".join(THAI_DIGIT_NAMES[d] for d in text if d in THAI_DIGIT_NAMES)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def expand_license_plate(plate: str) -> str:
    """
    Expand a Thai license plate for TTS pronunciation.

    Consonants are spelled out by name; digits are read one by one.

    Examples:
        "กท 1234"  → "กอ ไก่ ทอ ทหาร หนึ่ง สอง สาม สี่"
        "กขค 99"   → "กอ ไก่ ขอ ไข่ คอ ควาย เก้า เก้า"
    """
    m = _PLATE_RE.fullmatch(plate.strip())
    if m:
        return _spell_consonants(m.group(1)) + " " + _spell_digits(m.group(2))

    # Fallback: expand character by character
    parts: list[str] = []
    for char in plate:
        if char in THAI_CONSONANT_NAMES:
            parts.append(THAI_CONSONANT_NAMES[char])
        elif char in THAI_DIGIT_NAMES:
            parts.append(THAI_DIGIT_NAMES[char])
        elif char.strip():
            parts.append(char)
    return " ".join(parts)


def expand_province_code(code: str) -> str:
    """Return full province name for a known abbreviation, else return as-is."""
    return PROVINCE_NAMES.get(code.strip(), code)


def preprocess_for_tts(text: str) -> str:
    """
    Preprocess a Thai text string before sending to TTS.

    - Detects Thai license plate patterns and spells them out phonetically.
    - Expands known province abbreviations to their full names.

    Examples:
        "ทะเบียน กท 1234"
        → "ทะเบียน กอ ไก่ ทอ ทหาร หนึ่ง สอง สาม สี่"

        "รถจอดที่ กทม"
        → "รถจอดที่ กรุงเทพมหานคร"

        "ทะเบียน กท 1234 จด กทม"
        → "ทะเบียน กอ ไก่ ทอ ทหาร หนึ่ง สอง สาม สี่ จด กรุงเทพมหานคร"
    """
    # 1. Expand license plates first (so province abbreviations inside plates
    #    are not accidentally expanded by the province pass)
    result = _PLATE_RE.sub(
        lambda m: _spell_consonants(m.group(1)) + " " + _spell_digits(m.group(2)),
        text,
    )

    # 2. Expand standalone province codes
    result = _PROVINCE_RE.sub(lambda m: PROVINCE_NAMES.get(m.group(1), m.group(1)), result)

    return result
