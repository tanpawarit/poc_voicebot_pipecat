"""OpenAI-backed stage router for the scripted collection flow."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping, cast

from openai import AsyncOpenAI
from pydantic import create_model

from common.flows.collection import (
    BusyIntent,
    CollectionStage,
    ConfirmPtpOverdueIntent,
    Convince2Intent,
    ConvinceIntent,
    FAQIntent,
    OpeningIntent,
    PaymentInquiryIntent,
    StageIntent,
    VerifyIntent,
)

RouteEnum = (
    type[OpeningIntent]
    | type[BusyIntent]
    | type[VerifyIntent]
    | type[PaymentInquiryIntent]
    | type[ConfirmPtpOverdueIntent]
    | type[ConvinceIntent]
    | type[Convince2Intent]
    | type[FAQIntent]
)


@dataclass(frozen=True)
class _ClassificationSpec:
    route_enum: RouteEnum
    instructions: str
    build_input: Callable[[str, Mapping[str, object] | None], str]


def _amount(state: Mapping[str, object] | None) -> str:
    state = state or {}
    return str(
        state.get("total_of_overdue_amt")
        or state.get("due_amount")
        or "unknown"
    ).strip() or "unknown"


def _due_date(state: Mapping[str, object] | None) -> str:
    state = state or {}
    return str(state.get("due_dte") or state.get("due_date") or "unknown").strip() or "unknown"


def _deadline(state: Mapping[str, object] | None) -> str:
    return str((state or {}).get("deadline") or "unknown").strip() or "unknown"


def _build_opening_input(transcript: str, state: Mapping[str, object] | None) -> str:
    customer_name = str((state or {}).get("customer_name", "")).strip() or "unknown"
    return (
        f"customer_name: {customer_name}\n"
        f"user_reply: {transcript}\n\n"
        "Examples:\n"
        "- 'ครับ พูดอยู่ครับ' => target\n"
        "- 'ตอนนี้ไม่ว่างครับ โทรมาใหม่' => busy\n"
        "- 'เขาไม่อยู่ค่ะ เบอร์นี้เป็นพี่สาว' => other_person\n"
        "- 'leave your message after the tone' => voicemail\n"
        "- 'โทรมาเรื่องอะไรคะ' => faq\n"
        "- 'เอ่อ...' => unknown\n"
    )


def _build_verify_input(transcript: str, state: Mapping[str, object] | None) -> str:
    state = state or {}
    first_name = str(state.get("first_name", "")).strip() or "unknown"
    lic_no = str(state.get("lic_no", "")).strip() or "unknown"
    province = str(state.get("province", "")).strip() or "unknown"
    return (
        f"first_name: {first_name}\n"
        f"lic_no: {lic_no}\n"
        f"province: {province}\n"
        f"user_reply: {transcript}\n\n"
        "Examples:\n"
        "- 'ใช่ครับ รถผมเอง' => confirmed\n"
        "- 'ตอนนี้ไม่สะดวกคุย โทรมาใหม่ได้ไหม' => target_unavailable\n"
        "- 'ไม่ใช่ค่ะ ฉันเป็นภรรยาเขา' => third_party_speaking\n"
        "- 'โทรมาเรื่องอะไรคะ' => faq\n"
        "- 'เอ่อ...' => unknown\n"
    )


def _build_busy_input(transcript: str, state: Mapping[str, object] | None) -> str:
    return (
        f"user_reply: {transcript}\n\n"
        "Examples:\n"
        "- 'โทรมาอีกทีพรุ่งนี้บ่ายสองได้ไหม' => in_time\n"
        "- 'เย็นนี้หกโมงโทรมาใหม่' => today\n"
        "- 'โทรพรุ่งนี้สี่ทุ่มนะ' => out_time\n"
        "- 'ใครโทรมา' => faq\n"
        "- 'เอ่อ...' => unknown\n"
    )


def _build_payment_inquiry_input(transcript: str, state: Mapping[str, object] | None) -> str:
    return (
        f"amount_due: {_amount(state)}\n"
        f"due_date: {_due_date(state)}\n"
        f"deadline: {_deadline(state)}\n"
        f"user_reply: {transcript}\n\n"
        "Examples:\n"
        "- 'วันนี้จะโอนให้ครับ' => ptp\n"
        "- 'จ่ายแล้วครับ เมื่อเช้านี้' => paid\n"
        "- 'ยังไม่มีเงิน ขอไว้ก่อน' => convince\n"
        "- 'ยอดเท่าไหร่' => faq\n"
        "- 'เอ่อ...' => unknown\n"
    )


def _build_confirm_ptp_overdue_input(transcript: str, state: Mapping[str, object] | None) -> str:
    return (
        f"amount_due: {_amount(state)}\n"
        f"promised_payment_date: {str((state or {}).get('ptp_date') or 'unknown').strip() or 'unknown'}\n"
        f"deadline: {_deadline(state)}\n"
        f"user_reply: {transcript}\n\n"
        "Examples:\n"
        "- 'วันนี้จะจ่ายตามนัดครับ' => ptp\n"
        "- 'ผมจ่ายไปแล้ว' => paid\n"
        "- 'ยังไม่พร้อมจ่าย' => convince\n"
        "- 'โทรมาเรื่องอะไรนะ' => faq\n"
        "- 'เอ่อ...' => unknown\n"
    )


def _build_convince_input(transcript: str, state: Mapping[str, object] | None) -> str:
    return (
        f"amount_due: {_amount(state)}\n"
        f"deadline: {_deadline(state)}\n"
        f"user_reply: {transcript}\n\n"
        "Examples:\n"
        "- 'โอเค วันนี้จะชำระให้' => ptp\n"
        "- 'เพิ่งจ่ายไปแล้ว' => paid\n"
        "- 'วันนี้ยังไม่ไหว ขอเป็นพรุ่งนี้หรือวันอื่น' => convince2\n"
        "- 'ชำระได้ช่องทางไหนบ้าง' => faq\n"
        "- 'เอ่อ...' => unknown\n"
    )


def _build_convince2_input(transcript: str, state: Mapping[str, object] | None) -> str:
    return (
        f"amount_due: {_amount(state)}\n"
        f"deadline: {_deadline(state)}\n"
        f"user_reply: {transcript}\n\n"
        "Examples:\n"
        "- 'ได้ค่ะ พรุ่งนี้จะชำระให้' => ptp_convinced\n"
        "- 'จ่ายแล้วค่ะ' => paid\n"
        "- 'ไม่สะดวกจ่ายจริง ๆ' => refuse\n"
        "- 'ขอทราบยอดอีกที' => faq\n"
        "- 'เอ่อ...' => unknown\n"
    )


def _build_faq_input(transcript: str, state: Mapping[str, object] | None) -> str:
    customer_name = str((state or {}).get("customer_name", "")).strip() or "unknown"
    return (
        f"customer_name: {customer_name}\n"
        f"amount_due: {_amount(state)}\n"
        f"due_date: {_due_date(state)}\n"
        f"user_reply: {transcript}\n\n"
        "Examples:\n"
        "- 'โทรมาทำไม' => why_call\n"
        "- 'ใครโทรมา' => who_call\n"
        "- 'เป็น AI เหรอ' => why_ai\n"
        "- 'เอาเบอร์ฉันมาจากไหน' => privacy_concern\n"
        "- 'โอนสายให้เจ้าหน้าที่หน่อย' => agent_transfer\n"
        "- 'ยอดเท่าไหร่' => payment_amount\n"
        "- 'ครบกำหนดวันไหน' => payment_date\n"
        "- 'จ่ายได้ช่องทางไหนบ้าง' => payment_methods\n"
        "- 'ขอปรับโครงสร้างหนี้' => outscope\n"
        "- 'เอ่อ...' => unknown\n"
    )


_STAGE_CLASSIFICATION_SPECS: dict[CollectionStage, _ClassificationSpec] = {
    CollectionStage.OPENING: _ClassificationSpec(
        route_enum=OpeningIntent,
        instructions=(
            "Classify the reply to a Thai debt-collection opening greeting into exactly one "
            "route enum. Return only the route field. "
            "Use 'target' when the requested person is speaking, listening, or confirms they "
            "are the requested person. "
            "Use 'busy' when the requested person is on the line but unavailable, asks for a "
            "callback, or says they are not free to talk. "
            "Use 'other_person' when someone else answers, says the target is unavailable, "
            "says it is a wrong number, or requests a number change. "
            "Use 'voicemail' when the transcript sounds like an answering machine, "
            "automated greeting, voicemail prompt, or instruction to leave a message. "
            "Use 'faq' when the callee asks who is calling, what the call is about, why the "
            "bot is calling, or otherwise asks for clarification instead of confirming "
            "identity. "
            "Use 'unknown' only when the reply is too unclear or mixed to classify "
            "confidently."
        ),
        build_input=_build_opening_input,
    ),
    CollectionStage.BUSY: _ClassificationSpec(
        route_enum=BusyIntent,
        instructions=(
            "Classify the reply to a Thai callback-time question into exactly one route enum. "
            "Return only the route field. "
            "Use 'today' when the customer asks for a callback later today. "
            "Use 'in_time' when the customer gives a callback time within normal working hours "
            "on a later date or a generally acceptable callback time. "
            "Use 'out_time' when the customer gives a callback time outside normal working "
            "hours. "
            "Use 'faq' when the customer asks a clarifying question instead of giving a time. "
            "Use 'unknown' only when the reply is too unclear or mixed to classify "
            "confidently."
        ),
        build_input=_build_busy_input,
    ),
    CollectionStage.VERIFY: _ClassificationSpec(
        route_enum=VerifyIntent,
        instructions=(
            "Classify the reply to a Thai debt-collection verify question into exactly one "
            "route enum. Return only the route field. "
            "Use 'confirmed' when the speaker confirms they are the customer or confirms the "
            "vehicle ownership details. "
            "Use 'target_unavailable' when the correct customer is busy, unavailable, or "
            "asks for a callback instead of completing verification. "
            "Use 'third_party_speaking' when another person is speaking, the speaker denies "
            "being the owner, or indicates they are not the target customer. "
            "Use 'faq' when the speaker asks who is calling, what the call is about, why the "
            "bot needs the information, or asks for clarification instead of answering. "
            "Use 'unknown' only when the reply is too unclear or mixed to classify "
            "confidently."
        ),
        build_input=_build_verify_input,
    ),
    CollectionStage.PAYMENT_INQUIRY: _ClassificationSpec(
        route_enum=PaymentInquiryIntent,
        instructions=(
            "Classify the reply to a Thai debt-collection payment inquiry into exactly one "
            "route enum. Return only the route field. "
            "Use 'ptp' when the customer promises to pay now, today, or within an acceptable "
            "near-term timeframe. "
            "Use 'paid' when the customer says payment has already been completed. "
            "Use 'convince' when the customer cannot pay now, refuses, lacks funds, asks to "
            "pay later, or signals the agent should try persuasive follow-up instead of "
            "closing. "
            "Use 'faq' when the customer asks about amount, due date, payment methods, who is "
            "calling, or similar clarifying questions instead of directly answering. "
            "Use 'unknown' only when the reply is too unclear or mixed to classify "
            "confidently."
        ),
        build_input=_build_payment_inquiry_input,
    ),
    CollectionStage.CONFIRM_PTP_OVERDUE: _ClassificationSpec(
        route_enum=ConfirmPtpOverdueIntent,
        instructions=(
            "Classify the reply to a Thai debt-collection follow-up about a previous payment "
            "promise into exactly one route enum. Return only the route field. "
            "Use 'ptp' when the customer says they will still make the promised payment now or "
            "very soon. "
            "Use 'paid' when the customer says payment has already been completed. "
            "Use 'convince' when the customer has still not paid, cannot pay now, refuses, or "
            "needs further persuasion. "
            "Use 'faq' when the customer asks a clarifying question instead of answering. "
            "Use 'unknown' only when the reply is too unclear or mixed to classify "
            "confidently."
        ),
        build_input=_build_confirm_ptp_overdue_input,
    ),
    CollectionStage.CONVINCE: _ClassificationSpec(
        route_enum=ConvinceIntent,
        instructions=(
            "Classify the reply to a Thai debt-collection persuade-to-pay-today prompt into "
            "exactly one route enum. Return only the route field. "
            "Use 'ptp' when the customer agrees to pay today or agrees to make a payment "
            "promptly. "
            "Use 'paid' when the customer says payment has already been completed. "
            "Use 'convince2' when the customer still cannot pay today or asks to pay later, so "
            "the bot should try a second softer persuasion for tomorrow. "
            "Use 'faq' when the customer asks a clarifying question instead of answering. "
            "Use 'unknown' only when the reply is too unclear or mixed to classify "
            "confidently."
        ),
        build_input=_build_convince_input,
    ),
    CollectionStage.CONVINCE2: _ClassificationSpec(
        route_enum=Convince2Intent,
        instructions=(
            "Classify the reply to a Thai debt-collection persuade-to-pay-by-tomorrow prompt "
            "into exactly one route enum. Return only the route field. "
            "Use 'ptp_convinced' when the customer agrees to make the requested payment after "
            "this second attempt. "
            "Use 'paid' when the customer says payment has already been completed. "
            "Use 'refuse' when the customer still refuses, cannot commit, or remains unable to "
            "pay after the second persuasion. "
            "Use 'faq' when the customer asks a clarifying question instead of answering. "
            "Use 'unknown' only when the reply is too unclear or mixed to classify "
            "confidently."
        ),
        build_input=_build_convince2_input,
    ),
}

_FAQ_CLASSIFICATION_SPEC = _ClassificationSpec(
    route_enum=FAQIntent,
    instructions=(
        "Classify the Thai customer's clarification question into exactly one FAQ route enum. "
        "Return only the route field. "
        "Use 'why_ai' when they ask whether they are speaking to a bot or AI. "
        "Use 'who_call' when they ask who is calling. "
        "Use 'why_call' when they ask what the call is about or why the call was made. "
        "Use 'scam_call' when they worry the call is fake, suspicious, or a scam. "
        "Use 'privacy_concern' when they ask where the phone number or personal information "
        "came from. "
        "Use 'agent_transfer' when they ask to speak with a human agent. "
        "Use 'repeat' when they ask the bot to repeat the amount or repeat the latest payment "
        "instruction. "
        "Use 'payment_amount' when they ask for the amount due. "
        "Use 'payment_date' when they ask for the due date or payment deadline. "
        "Use 'why_call_again' when they complain about repeated calls. "
        "Use 'payment_methods' when they ask how or where to pay. "
        "Use 'outscope' when they ask for things outside this bot's remit, such as debt "
        "restructuring, disputes, statements, payment cycle changes, payment history, interest, "
        "fees, or payoff balance. "
        "Use 'unknown' only when the question is too unclear to classify confidently."
    ),
    build_input=_build_faq_input,
)


class OpenAIIntentClassifier:
    """Route caller replies to the next scripted step using OpenAI."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def _classify(
        self,
        *,
        spec_name: str,
        spec: _ClassificationSpec,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> StrEnum:
        normalized_transcript = transcript.strip()
        if not normalized_transcript:
            raise ValueError("Transcript is empty")

        response_model = create_model(
            f"{spec_name}Classification",
            route=(spec.route_enum, ...),
        )
        response = await self._client.responses.parse(
            model=self._model,
            temperature=0,
            max_output_tokens=32,
            instructions=spec.instructions,
            input=spec.build_input(normalized_transcript, state),
            text_format=response_model,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError(f"OpenAI did not return a parsed route for {spec_name}")

        route = getattr(parsed, "route", None)
        if route is None or not isinstance(route, spec.route_enum):
            raise ValueError(f"OpenAI returned an invalid route for {spec_name}")
        return route

    async def classify_stage(
        self,
        stage: CollectionStage,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> StageIntent:
        return cast(
            StageIntent,
            await self._classify(
                spec_name=f"{stage.value.title()}Route",
                spec=_STAGE_CLASSIFICATION_SPECS[stage],
                transcript=transcript,
                state=state,
            ),
        )

    async def classify_opening(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> OpeningIntent:
        return cast(
            OpeningIntent,
            await self.classify_stage(CollectionStage.OPENING, transcript, state),
        )

    async def classify_verify(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> VerifyIntent:
        return cast(
            VerifyIntent,
            await self.classify_stage(CollectionStage.VERIFY, transcript, state),
        )

    async def classify_busy(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> BusyIntent:
        return cast(
            BusyIntent,
            await self.classify_stage(CollectionStage.BUSY, transcript, state),
        )

    async def classify_payment_inquiry(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> PaymentInquiryIntent:
        return cast(
            PaymentInquiryIntent,
            await self.classify_stage(CollectionStage.PAYMENT_INQUIRY, transcript, state),
        )

    async def classify_convince(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> ConvinceIntent:
        return cast(
            ConvinceIntent,
            await self.classify_stage(CollectionStage.CONVINCE, transcript, state),
        )

    async def classify_convince2(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> Convince2Intent:
        return cast(
            Convince2Intent,
            await self.classify_stage(CollectionStage.CONVINCE2, transcript, state),
        )

    async def classify_faq(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> FAQIntent:
        return cast(
            FAQIntent,
            await self._classify(
                spec_name="FAQRoute",
                spec=_FAQ_CLASSIFICATION_SPEC,
                transcript=transcript,
                state=state,
            ),
        )

    async def classify(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> OpeningIntent:
        """Backward-compatible alias for opening-stage classification."""
        return await self.classify_opening(transcript, state)


class OpenAIVerifyIntentClassifier(OpenAIIntentClassifier):
    """Backward-compatible wrapper for verify-stage routing."""

    async def classify(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> VerifyIntent:
        return await self.classify_verify(transcript, state)


__all__ = [
    "OpenAIIntentClassifier",
    "OpenAIVerifyIntentClassifier",
    "StageIntent",
]
