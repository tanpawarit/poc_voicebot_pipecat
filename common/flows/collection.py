"""Deterministic collection flow definition for the multi-step collection POC."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, TypeAlias


def _fmt(template: str, state: Mapping[str, object]) -> str:
    """Safe string format - missing keys are left as-is."""
    try:
        return template.format(**state)
    except KeyError:
        return template


def _normalize_state(state: Mapping[str, object] | None) -> dict[str, object]:
    normalized = dict(state or {})

    if "total_of_overdue_amt" not in normalized and "due_amount" in normalized:
        normalized["total_of_overdue_amt"] = normalized["due_amount"]

    if "due_dte" not in normalized and "due_date" in normalized:
        normalized["due_dte"] = normalized["due_date"]

    return normalized


def _default_stage_from_state(state: Mapping[str, object]) -> "CollectionStage":
    checkpoint = str(state.get("checkpoint") or state.get("start_stage") or "").strip()
    if not checkpoint:
        return CollectionStage.OPENING

    aliases = {
        "overdue": CollectionStage.PAYMENT_INQUIRY,
    }
    if checkpoint in aliases:
        return aliases[checkpoint]

    try:
        return CollectionStage(checkpoint)
    except ValueError:
        return CollectionStage.OPENING


class OpeningIntent(StrEnum):
    TARGET = "target"
    BUSY = "busy"
    OTHER_PERSON = "other_person"
    VOICEMAIL = "voicemail"
    FAQ = "faq"
    UNKNOWN = "unknown"


CollectionIntent = OpeningIntent


class BusyIntent(StrEnum):
    TODAY = "today"
    IN_TIME = "in_time"
    OUT_TIME = "out_time"
    FAQ = "faq"
    UNKNOWN = "unknown"


class VerifyIntent(StrEnum):
    CONFIRMED = "confirmed"
    TARGET_UNAVAILABLE = "target_unavailable"
    THIRD_PARTY_SPEAKING = "third_party_speaking"
    FAQ = "faq"
    UNKNOWN = "unknown"


class PaymentInquiryIntent(StrEnum):
    PTP = "ptp"
    PAID = "paid"
    CONVINCE = "convince"
    FAQ = "faq"
    UNKNOWN = "unknown"


class ConfirmPtpOverdueIntent(StrEnum):
    PTP = "ptp"
    PAID = "paid"
    CONVINCE = "convince"
    FAQ = "faq"
    UNKNOWN = "unknown"


class ConvinceIntent(StrEnum):
    PTP = "ptp"
    PAID = "paid"
    CONVINCE2 = "convince2"
    FAQ = "faq"
    UNKNOWN = "unknown"


class Convince2Intent(StrEnum):
    PTP_CONVINCED = "ptp_convinced"
    PAID = "paid"
    REFUSE = "refuse"
    FAQ = "faq"
    UNKNOWN = "unknown"


class FAQIntent(StrEnum):
    WHY_AI = "why_ai"
    WHO_CALL = "who_call"
    WHY_CALL = "why_call"
    SCAM_CALL = "scam_call"
    PRIVACY_CONCERN = "privacy_concern"
    AGENT_TRANSFER = "agent_transfer"
    REPEAT = "repeat"
    PAYMENT_AMOUNT = "payment_amount"
    PAYMENT_DATE = "payment_date"
    WHY_CALL_AGAIN = "why_call_again"
    PAYMENT_METHODS = "payment_methods"
    OUTSCOPE = "outscope"
    UNKNOWN = "unknown"


class CollectionStage(StrEnum):
    OPENING = "opening"
    BUSY = "busy"
    VERIFY = "verify"
    PAYMENT_INQUIRY = "payment_inquiry"
    CONFIRM_PTP_OVERDUE = "confirm_ptp_overdue"
    CONVINCE = "convince"
    CONVINCE2 = "convince2"


StageIntent: TypeAlias = (
    OpeningIntent
    | BusyIntent
    | VerifyIntent
    | PaymentInquiryIntent
    | ConfirmPtpOverdueIntent
    | ConvinceIntent
    | Convince2Intent
)


@dataclass(frozen=True)
class StageRoute:
    next_stage: CollectionStage | None = None
    response: str | None = None


@dataclass(frozen=True)
class StageDefinition:
    prompt: str
    retry_prompt: str
    routes: dict[StageIntent, StageRoute]


@dataclass(frozen=True)
class CollectionFlowDefinition:
    stages: dict[CollectionStage, StageDefinition]
    faq_responses: dict[FAQIntent, str]
    fallback: str
    default_stage: CollectionStage = CollectionStage.OPENING

    def prompt_for(self, stage: CollectionStage, *, retry: bool = False) -> str:
        stage_definition = self.stages[stage]
        return stage_definition.retry_prompt if retry else stage_definition.prompt

    def route_for(self, stage: CollectionStage, intent: StageIntent) -> StageRoute:
        return self.stages[stage].routes.get(intent, StageRoute(response=self.fallback))

    def faq_response_for(self, intent: FAQIntent) -> str:
        return self.faq_responses.get(intent, self.fallback)

    def prewarm_texts(self) -> tuple[str, ...]:
        """Return the non-opening prompts worth prewarming for TTS."""
        candidates: list[str] = []
        for stage_definition in self.stages.values():
            candidates.extend([stage_definition.prompt, stage_definition.retry_prompt])
            for route in stage_definition.routes.values():
                if route.response:
                    candidates.append(route.response)

        candidates.extend(self.faq_responses.values())
        candidates.append(self.fallback)

        excluded = {
            self.prompt_for(self.default_stage),
            self.prompt_for(self.default_stage, retry=True),
        }
        seen: set[str] = set()
        result: list[str] = []
        for text in candidates:
            if not text or text in excluded or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return tuple(result)


_OPENING_TEMPLATE = (
    "สวัสดีค่ะ ดิฉันน้องใจ จากบริษัทเงินให้ใจจำกัด "
    "ขอเรียนสายคุณ {customer_name} ค่ะ"
)

_OPENING_RETRY_TEMPLATE = "ไม่ทราบว่าดิฉันกำลังเรียนสายกับคุณ {customer_name} อยู่หรือเปล่าคะ"

_BUSY_TEMPLATE = "ขออภัยที่รบกวนเวลาค่ะ ไม่ทราบว่าสะดวกให้ติดต่อกลับมาอีกครั้งเวลาไหนดีคะ"

_BUSY_RETRY_TEMPLATE = "ไม่ทราบว่าสะดวกให้ติดต่อกลับมาอีกครั้งเวลาไหนดีคะ"

_VERIFY_TEMPLATE = (
    "ขอบคุณค่ะ น้องใจขออนุญาตยืนยันข้อมูลนะคะ "
    "คุณ {first_name} เป็นเจ้าของรถทะเบียน {lic_no}, {province} ใช่มั้ยคะ"
)

_VERIFY_RETRY_TEMPLATE = "คุณเป็นเจ้าของรถทะเบียน {lic_no} ใช่มั้ยคะ"

_PAYMENT_INQUIRY_TEMPLATE = (
    "ขอบคุณค่ะ ทั้งนี้ เพื่อพัฒนาคุณภาพการให้บริการ "
    "ทางบริษัทฯ จะมีการบันทึกเสียงการสนทนานะคะ "
    "วันนี้น้องใจขออนุญาตติดต่อ เรื่องสินเชื่อรถทะเบียน {lic_no}, {province} ค่ะ "
    "คือน้องใจจะรบกวนสอบถามเรื่องยอดเรียกเก็บในเดือนปัจจุบัน "
    "ไม่ทราบว่าคุณลูกค้าได้ชำระเข้ามาแล้วหรือยังคะ"
)

_PAYMENT_INQUIRY_RETRY_TEMPLATE = "คุณลูกค้าได้ดำเนินการชำระเข้ามาแล้วหรือยังคะ"

_CONFIRM_PTP_OVERDUE_TEMPLATE = (
    "ขอบคุณค่ะ ทั้งนี้ เพื่อพัฒนาคุณภาพการให้บริการ "
    "ทางบริษัทฯ จะมีการบันทึกเสียงการสนทนานะคะ "
    "วันนี้น้องใจขออนุญาตติดต่อ เรื่องสินเชื่อรถทะเบียน {lic_no}, {province} ค่ะ "
    "ลูกค้าได้ชำระยอดตามที่นัดชำระหรือยังคะ"
)

_CONFIRM_PTP_OVERDUE_RETRY_TEMPLATE = "ลูกค้าได้ชำระยอดตามที่นัดชำระหรือยังคะ"

_CONVINCE_TEMPLATE = (
    "น้องใจขอแจ้งยอดเรียกเก็บนะคะ "
    "ยอดที่แจ้งรวมค่าปรับและค่าติดตามทวงถามหนี้เป็นจำนวน "
    "{total_of_overdue_amt} บาท "
    "กรุณาชำระภายในวันนี้ สะดวกไหมคะ"
)

_CONVINCE_RETRY_TEMPLATE = "คุณลูกค้าสะดวกชำระภายในวันนี้มั้ยคะ"

_CONVINCE2_TEMPLATE = (
    "เพื่อรักษาเครดิตและประวัติการชำระ "
    "น้องใจขอแนะนำให้คุณลูกค้าชำระเงินภายในวันพรุ่งนี้ค่ะ "
    "การชำระจะช่วยให้ภาระค่าใช้จ่ายในอนาคตของคุณลูกค้าลดลงด้วยนะคะ "
    "กรุณาชำระเข้ามาภายในวันพรุ่งนี้ได้ไหมคะ"
)

_CONVINCE2_RETRY_TEMPLATE = "คุณลูกค้าสะดวกชำระภายในวันพรุ่งนี้มั้ยคะ"

_BUSY_TODAY_TEMPLATE = (
    "เวลาลูกค้าแจ้งมา น้องใจไม่สามารถให้บริการตามเวลาลูกค้าแจ้งได้ "
    "ขออนุญาตติดต่อใหม่ภายหลังนะคะ สวัสดีค่ะ"
)

_BUSY_IN_TIME_TEMPLATE = "น้องใจขออนุญาตติดต่อใหม่ตามวันที่ลูกค้าแจ้งได้นะคะ สวัสดีค่ะ"

_BUSY_OUT_TIME_TEMPLATE = (
    "เวลาลูกค้าแจ้งมา น้องใจไม่สามารถให้บริการตามเวลาที่แจ้งได้ "
    "ขออนุญาตติดต่อใหม่ภายในเวลาทำการนะคะ สวัสดีค่ะ"
)

_OTHER_PERSON_TEMPLATE = "ขออภัยค่ะ ขออนุญาตวางสายค่ะ"

_VOICEMAIL_TEMPLATE = "ขออนุญาตติดต่อใหม่ภายหลังนะคะ สวัสดีค่ะ"

_GENERIC_FAQ_TEMPLATE = (
    "ดิฉันน้องใจ ได้รับมอบหมายจากบริษัทเงินให้ใจ "
    "มีหน้าที่แนะนำช่องทางการชำระเงินของบริษัทค่ะ"
)

_FAQ_WHY_AI_TEMPLATE = "ดิฉันน้องใจ ได้รับมอบหมายจากบริษัทเงินให้ใจค่ะ"

_FAQ_PRIVACY_TEMPLATE = (
    "ไม่ต้องกังวลนะคะ ทางเราได้เบอร์โทรศัพท์ของคุณจากฐานข้อมูลลูกค้าสัมพันธ์ "
    "ซึ่งคุณได้เคยให้ข้อมูลเอาไว้ค่ะ"
)

_FAQ_AGENT_TRANSFER_TEMPLATE = (
    "น้องใจไม่สามารถโอนสายให้เจ้าหน้าที่ได้นะคะ "
    "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ"
)

_FAQ_REPEAT_TEMPLATE = "คุณลูกค้ามียอดเรียกเก็บจำนวน {total_of_overdue_amt} บาทค่ะ"

_FAQ_PAYMENT_AMOUNT_TEMPLATE = (
    "สินเชื่อของคุณมียอดชำระจำนวน {total_of_overdue_amt} บาทค่ะ"
)

_FAQ_PAYMENT_DATE_TEMPLATE = "กำหนดชำระเป็นวันที่ {due_dte} ค่ะ"

_FAQ_WHY_CALL_AGAIN_TEMPLATE = (
    "ขออภัยในความไม่สะดวกค่ะ ทางเราจะปรับปรุงการให้บริการให้ดียิ่งขึ้น "
    "ขอบคุณที่ใช้บริการเงินให้ใจ สวัสดีค่ะ"
)

_FAQ_PAYMENT_METHODS_TEMPLATE = (
    "ลูกค้าสามารถชำระผ่าน App K PLUS สาขาหรือตู้ ATM ธนาคารกสิกรไทย "
    "ผ่าน Mobile Banking ที่รองรับการสแกน QR Code "
    "หรือชำระเงินสดที่เคาน์เตอร์เซอร์วิสในร้านเซเว่นอีเลฟเว่นทั่วประเทศได้ค่ะ"
)

_FAQ_OUTSCOPE_TEMPLATE = (
    "ขออภัยค่ะ น้องใจยังไม่สามารถให้บริการเรื่องนี้ได้ "
    "หากลูกค้าต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ"
)

_FALLBACK_TEMPLATE = (
    "ขออภัยค่ะ น้องใจจะแจ้งให้เจ้าหน้าที่ติดต่อกลับอีกครั้ง สวัสดีค่ะ"
)

_PTP_TEMPLATE = (
    "น้องใจขอบคุณที่ใช้บริการบริษัทเงินให้ใจจำกัด "
    "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ สวัสดีค่ะ"
)

_PAID_TEMPLATE = (
    "น้องใจขอบคุณสำหรับการชำระเงินและใช้บริการบริษัทเงินให้ใจจำกัด "
    "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ สวัสดีค่ะ"
)

_REFUSE_TEMPLATE = (
    "หากลูกค้ายังไม่สะดวก ไม่เป็นไรค่ะ น้องใจขออนุญาตติดต่อหาลูกค้าอีกครั้งนะคะ "
    "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ "
    "ขอบคุณที่ใช้บริการบริษัทเงินให้ใจจำกัด สวัสดีค่ะ"
)


def build_collection_flow(state: Mapping[str, object] | None = None) -> CollectionFlowDefinition:
    """Build the deterministic collection scripts from CRM state."""
    s = _normalize_state(state)
    fallback = _fmt(_FALLBACK_TEMPLATE, s)
    generic_faq = _fmt(_GENERIC_FAQ_TEMPLATE, s)
    ptp = _fmt(_PTP_TEMPLATE, s)
    paid = _fmt(_PAID_TEMPLATE, s)
    refuse = _fmt(_REFUSE_TEMPLATE, s)

    stages = {
        CollectionStage.OPENING: StageDefinition(
            prompt=_fmt(_OPENING_TEMPLATE, s),
            retry_prompt=_fmt(_OPENING_RETRY_TEMPLATE, s),
            routes={
                OpeningIntent.TARGET: StageRoute(next_stage=CollectionStage.VERIFY),
                OpeningIntent.BUSY: StageRoute(next_stage=CollectionStage.BUSY),
                OpeningIntent.OTHER_PERSON: StageRoute(response=_fmt(_OTHER_PERSON_TEMPLATE, s)),
                OpeningIntent.VOICEMAIL: StageRoute(response=_fmt(_VOICEMAIL_TEMPLATE, s)),
            },
        ),
        CollectionStage.BUSY: StageDefinition(
            prompt=_fmt(_BUSY_TEMPLATE, s),
            retry_prompt=_fmt(_BUSY_RETRY_TEMPLATE, s),
            routes={
                BusyIntent.TODAY: StageRoute(response=_fmt(_BUSY_TODAY_TEMPLATE, s)),
                BusyIntent.IN_TIME: StageRoute(response=_fmt(_BUSY_IN_TIME_TEMPLATE, s)),
                BusyIntent.OUT_TIME: StageRoute(response=_fmt(_BUSY_OUT_TIME_TEMPLATE, s)),
            },
        ),
        CollectionStage.VERIFY: StageDefinition(
            prompt=_fmt(_VERIFY_TEMPLATE, s),
            retry_prompt=_fmt(_VERIFY_RETRY_TEMPLATE, s),
            routes={
                VerifyIntent.CONFIRMED: StageRoute(next_stage=CollectionStage.PAYMENT_INQUIRY),
                VerifyIntent.TARGET_UNAVAILABLE: StageRoute(next_stage=CollectionStage.BUSY),
                VerifyIntent.THIRD_PARTY_SPEAKING: StageRoute(
                    response=_fmt(_OTHER_PERSON_TEMPLATE, s)
                ),
            },
        ),
        CollectionStage.PAYMENT_INQUIRY: StageDefinition(
            prompt=_fmt(_PAYMENT_INQUIRY_TEMPLATE, s),
            retry_prompt=_fmt(_PAYMENT_INQUIRY_RETRY_TEMPLATE, s),
            routes={
                PaymentInquiryIntent.PTP: StageRoute(response=ptp),
                PaymentInquiryIntent.PAID: StageRoute(response=paid),
                PaymentInquiryIntent.CONVINCE: StageRoute(next_stage=CollectionStage.CONVINCE),
            },
        ),
        CollectionStage.CONFIRM_PTP_OVERDUE: StageDefinition(
            prompt=_fmt(_CONFIRM_PTP_OVERDUE_TEMPLATE, s),
            retry_prompt=_fmt(_CONFIRM_PTP_OVERDUE_RETRY_TEMPLATE, s),
            routes={
                ConfirmPtpOverdueIntent.PTP: StageRoute(response=ptp),
                ConfirmPtpOverdueIntent.PAID: StageRoute(response=paid),
                ConfirmPtpOverdueIntent.CONVINCE: StageRoute(next_stage=CollectionStage.CONVINCE),
            },
        ),
        CollectionStage.CONVINCE: StageDefinition(
            prompt=_fmt(_CONVINCE_TEMPLATE, s),
            retry_prompt=_fmt(_CONVINCE_RETRY_TEMPLATE, s),
            routes={
                ConvinceIntent.PTP: StageRoute(response=ptp),
                ConvinceIntent.PAID: StageRoute(response=paid),
                ConvinceIntent.CONVINCE2: StageRoute(next_stage=CollectionStage.CONVINCE2),
            },
        ),
        CollectionStage.CONVINCE2: StageDefinition(
            prompt=_fmt(_CONVINCE2_TEMPLATE, s),
            retry_prompt=_fmt(_CONVINCE2_RETRY_TEMPLATE, s),
            routes={
                Convince2Intent.PTP_CONVINCED: StageRoute(response=ptp),
                Convince2Intent.PAID: StageRoute(response=paid),
                Convince2Intent.REFUSE: StageRoute(response=refuse),
            },
        ),
    }

    faq_responses = {
        FAQIntent.WHY_AI: _fmt(_FAQ_WHY_AI_TEMPLATE, s),
        FAQIntent.WHO_CALL: generic_faq,
        FAQIntent.WHY_CALL: generic_faq,
        FAQIntent.SCAM_CALL: generic_faq,
        FAQIntent.PRIVACY_CONCERN: _fmt(_FAQ_PRIVACY_TEMPLATE, s),
        FAQIntent.AGENT_TRANSFER: _fmt(_FAQ_AGENT_TRANSFER_TEMPLATE, s),
        FAQIntent.REPEAT: _fmt(_FAQ_REPEAT_TEMPLATE, s),
        FAQIntent.PAYMENT_AMOUNT: _fmt(_FAQ_PAYMENT_AMOUNT_TEMPLATE, s),
        FAQIntent.PAYMENT_DATE: _fmt(_FAQ_PAYMENT_DATE_TEMPLATE, s),
        FAQIntent.WHY_CALL_AGAIN: _fmt(_FAQ_WHY_CALL_AGAIN_TEMPLATE, s),
        FAQIntent.PAYMENT_METHODS: _fmt(_FAQ_PAYMENT_METHODS_TEMPLATE, s),
        FAQIntent.OUTSCOPE: _fmt(_FAQ_OUTSCOPE_TEMPLATE, s),
    }

    return CollectionFlowDefinition(
        stages=stages,
        faq_responses=faq_responses,
        fallback=fallback,
        default_stage=_default_stage_from_state(s),
    )


__all__ = [
    "CollectionFlowDefinition",
    "CollectionIntent",
    "CollectionStage",
    "BusyIntent",
    "ConfirmPtpOverdueIntent",
    "Convince2Intent",
    "ConvinceIntent",
    "FAQIntent",
    "OpeningIntent",
    "PaymentInquiryIntent",
    "StageIntent",
    "StageRoute",
    "VerifyIntent",
    "build_collection_flow",
]
