"""Collection flow definition and Gemini Live prompt builder for the current POC."""

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
    verify: str
    responses: dict[CollectionIntent, str]
    fallback: str

    def response_for(self, intent: CollectionIntent) -> str:
        if intent == CollectionIntent.TARGET:
            return self.verify
        return self.responses.get(intent, self.fallback)


_OPENING_TEMPLATE = (
    "สวัสดีค่ะ ดิฉันน้องใจ จากบริษัทเงินให้ใจจำกัด "
    "ขอเรียนสายคุณ {customer_name} ค่ะ"
)

_VERIFY_SCRIPT_TEMPLATE = (
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
        verify=_fmt(_VERIFY_SCRIPT_TEMPLATE, s),
        responses={
            CollectionIntent.BUSY: _fmt(_BUSY_TEMPLATE, s),
            CollectionIntent.OTHER_PERSON: _fmt(_OTHER_PERSON_TEMPLATE, s),
            CollectionIntent.VOICEMAIL: _fmt(_VOICEMAIL_TEMPLATE, s),
        },
        fallback=fallback,
    )


def build_collection_gemini_system_instruction(
    state: Mapping[str, object] | None = None,
) -> str:
    """Build a strict Gemini Live instruction for the opening + verify collection POC."""
    s = state or {}
    flow = build_collection_flow(s)
    customer_name = str(s.get("customer_name", "")).strip() or "ลูกค้าที่ต้องการติดต่อ"
    return (
        "You are a Thai voice bot for a deterministic debt-collection POC.\n"
        "Follow the scripted call flow exactly and do not improvise.\n\n"
        f"Target customer name: {customer_name}\n\n"
        "Rules:\n"
        "- Speak naturally in Thai for a phone call.\n"
        f"- Start the call immediately with this exact opening line: {flow.opening}\n"
        "- After the callee replies once, decide internally between exactly four intents:\n"
        "  target = the requested person is speaking or confirms they are the requested person.\n"
        "  busy = the requested person is speaking but asks for a callback or says they are busy.\n"
        "  other_person = someone else answered or says the requested person is unavailable.\n"
        "  voicemail = an answering machine, automated greeting, or prompt to leave a message.\n"
        "- Then reply with exactly one matching scripted line and nothing else:\n"
        f"  target -> verify step: {flow.verify}\n"
        f"  busy: {flow.response_for(CollectionIntent.BUSY)}\n"
        f"  other_person: {flow.response_for(CollectionIntent.OTHER_PERSON)}\n"
        f"  voicemail: {flow.response_for(CollectionIntent.VOICEMAIL)}\n"
        f"- If you are unsure, use this fallback exactly: {flow.fallback}\n"
        "- Do not ask any extra questions beyond the scripted response.\n"
        "- Do not add filler, paraphrase the script, or continue the conversation after the scripted response.\n"
        "- After the scripted response, stay silent and wait for the call to end.\n"
    )


def build_collection_gemini_initial_messages(
    state: Mapping[str, object] | None = None,
) -> list[dict[str, str]]:
    """Seed Gemini Live with a kickoff turn so it speaks the opening first."""
    flow = build_collection_flow(state or {})
    return [
        {
            "role": "user",
            "content": (
                "The callee has just answered the phone. Start the call now and reply with "
                f"this exact opening line only: {flow.opening}"
            ),
        }
    ]


__all__ = [
    "CollectionFlowDefinition",
    "CollectionIntent",
    "build_collection_gemini_initial_messages",
    "build_collection_gemini_system_instruction",
    "build_collection_flow",
]
