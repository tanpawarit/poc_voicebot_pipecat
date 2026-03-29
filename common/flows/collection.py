"""Deterministic collection flow definition for the multi-step collection POC."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


def _fmt(template: str, state: Mapping[str, object]) -> str:
    """Safe string format - missing keys are left as-is."""
    try:
        return template.format(**state)
    except KeyError:
        return template


class CollectionIntent(StrEnum):
    TARGET = "target"
    BUSY = "busy"
    OTHER_PERSON = "other_person"
    VOICEMAIL = "voicemail"
    FAQ = "faq"
    UNKNOWN = "unknown"


class VerifyIntent(StrEnum):
    CONFIRMED = "confirmed"
    TARGET_UNAVAILABLE = "target_unavailable"
    THIRD_PARTY_SPEAKING = "third_party_speaking"
    FAQ = "faq"
    UNKNOWN = "unknown"


class CollectionStage(StrEnum):
    OPENING = "opening"
    VERIFY = "verify"


@dataclass(frozen=True)
class CollectionFlowDefinition:
    opening: str
    opening_retry: str
    opening_responses: dict[CollectionIntent, str]
    verify: str
    verify_retry: str
    verify_responses: dict[VerifyIntent, str]
    fallback: str

    def prompt_for(self, stage: CollectionStage, *, retry: bool = False) -> str:
        if stage == CollectionStage.OPENING:
            return self.opening_retry if retry else self.opening
        if stage == CollectionStage.VERIFY:
            return self.verify_retry if retry else self.verify
        raise ValueError(f"Unsupported collection stage: {stage!r}")

    def opening_response_for(self, intent: CollectionIntent) -> str:
        return self.opening_responses.get(intent, self.fallback)

    def verify_response_for(self, intent: VerifyIntent) -> str:
        return self.verify_responses.get(intent, self.fallback)


_OPENING_TEMPLATE = (
    "สวัสดีค่ะ ดิฉันน้องใจ จากบริษัทเงินให้ใจจำกัด "
    "ขอเรียนสายคุณ {customer_name} ค่ะ"
)

_OPENING_RETRY_TEMPLATE = "ไม่ทราบว่าดิฉันกำลังเรียนสายกับคุณ {customer_name} อยู่หรือเปล่าคะ"

_VERIFY_TEMPLATE = (
    "ขอบคุณค่ะ น้องใจขออนุญาตยืนยันข้อมูลนะคะ "
    "คุณ {first_name} เป็นเจ้าของรถทะเบียน {lic_no}, {province} ใช่มั้ยคะ"
)

_VERIFY_RETRY_TEMPLATE = "คุณเป็นเจ้าของรถทะเบียน {lic_no} ใช่มั้ยคะ"

_BUSY_TEMPLATE = (
    "ขออภัยที่รบกวนเวลาค่ะ น้องใจขออนุญาตติดต่อใหม่ภายหลังนะคะ สวัสดีค่ะ"
)

_OTHER_PERSON_TEMPLATE = "ขออภัยค่ะ ขออนุญาตวางสายค่ะ"

_VOICEMAIL_TEMPLATE = "ขออนุญาตติดต่อใหม่ภายหลังนะคะ สวัสดีค่ะ"

_FAQ_TEMPLATE = (
    "ดิฉันน้องใจ ได้รับมอบหมายจากบริษัทเงินให้ใจ "
    "มีหน้าที่แนะนำช่องทางการชำระเงินของบริษัทค่ะ"
)

_FALLBACK_TEMPLATE = (
    "ขออภัยค่ะ น้องใจจะแจ้งให้เจ้าหน้าที่ติดต่อกลับอีกครั้ง สวัสดีค่ะ"
)

_OVERDUE_TEMPLATE = (
    "ขอบคุณค่ะ ทั้งนี้ เพื่อพัฒนาคุณภาพการให้บริการ "
    "ทางบริษัทฯ จะมีการบันทึกเสียงการสนทนานะคะ "
    "วันนี้น้องใจขออนุญาตติดต่อ เรื่องสินเชื่อรถทะเบียน {lic_no}, {province} ค่ะ "
    "คือน้องใจจะรบกวนสอบถามเรื่องยอดเรียกเก็บในเดือนปัจจุบัน "
    "ไม่ทราบว่าคุณลูกค้าได้ชำระเข้ามาแล้วหรือยังคะ"
)


def build_collection_flow(state: Mapping[str, object] | None = None) -> CollectionFlowDefinition:
    """Build the deterministic collection scripts from CRM state."""
    s = state or {}
    fallback = _fmt(_FALLBACK_TEMPLATE, s)
    return CollectionFlowDefinition(
        opening=_fmt(_OPENING_TEMPLATE, s),
        opening_retry=_fmt(_OPENING_RETRY_TEMPLATE, s),
        opening_responses={
            CollectionIntent.BUSY: _fmt(_BUSY_TEMPLATE, s),
            CollectionIntent.OTHER_PERSON: _fmt(_OTHER_PERSON_TEMPLATE, s),
            CollectionIntent.VOICEMAIL: _fmt(_VOICEMAIL_TEMPLATE, s),
            CollectionIntent.FAQ: _fmt(_FAQ_TEMPLATE, s),
        },
        verify=_fmt(_VERIFY_TEMPLATE, s),
        verify_retry=_fmt(_VERIFY_RETRY_TEMPLATE, s),
        verify_responses={
            VerifyIntent.CONFIRMED: _fmt(_OVERDUE_TEMPLATE, s),
            VerifyIntent.TARGET_UNAVAILABLE: _fmt(_BUSY_TEMPLATE, s),
            VerifyIntent.THIRD_PARTY_SPEAKING: _fmt(_OTHER_PERSON_TEMPLATE, s),
            VerifyIntent.FAQ: _fmt(_FAQ_TEMPLATE, s),
        },
        fallback=fallback,
    )


__all__ = [
    "CollectionFlowDefinition",
    "CollectionIntent",
    "CollectionStage",
    "VerifyIntent",
    "build_collection_flow",
]
