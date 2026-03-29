"""Deterministic collection flow definition for the OpenAI cascaded POC."""

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


@dataclass(frozen=True)
class CollectionFlowDefinition:
    opening: str
    responses: dict[CollectionIntent, str]
    fallback: str

    def response_for(self, intent: CollectionIntent) -> str:
        return self.responses.get(intent, self.fallback)


_OPENING_TEMPLATE = (
    "สวัสดีค่ะ ดิฉันน้องใจ จากบริษัทเงินให้ใจจำกัด "
    "ขอเรียนสายคุณ {customer_name} ค่ะ"
)

_TARGET_TEMPLATE = (
    "ขอบคุณค่ะ น้องใจขออนุญาตยืนยันข้อมูลนะคะ "
    "คุณ {first_name} เป็นเจ้าของรถทะเบียน {lic_no} จังหวัด {province} ใช่ไหมคะ"
)

_BUSY_TEMPLATE = (
    "ขออภัยที่รบกวนเวลาค่ะ น้องใจขออนุญาตติดต่อใหม่ภายหลังนะคะ สวัสดีค่ะ"
)

_OTHER_PERSON_TEMPLATE = "ขออภัยค่ะ ขออนุญาตวางสายค่ะ"

_VOICEMAIL_TEMPLATE = "ขออนุญาตติดต่อใหม่ภายหลังนะคะ สวัสดีค่ะ"


def build_collection_flow(state: Mapping[str, object] | None = None) -> CollectionFlowDefinition:
    """Build the deterministic collection scripts from CRM state."""
    s = state or {}
    fallback = _fmt(_BUSY_TEMPLATE, s)
    return CollectionFlowDefinition(
        opening=_fmt(_OPENING_TEMPLATE, s),
        responses={
            CollectionIntent.TARGET: _fmt(_TARGET_TEMPLATE, s),
            CollectionIntent.BUSY: _fmt(_BUSY_TEMPLATE, s),
            CollectionIntent.OTHER_PERSON: _fmt(_OTHER_PERSON_TEMPLATE, s),
            CollectionIntent.VOICEMAIL: _fmt(_VOICEMAIL_TEMPLATE, s),
        },
        fallback=fallback,
    )


__all__ = [
    "CollectionFlowDefinition",
    "CollectionIntent",
    "build_collection_flow",
]
