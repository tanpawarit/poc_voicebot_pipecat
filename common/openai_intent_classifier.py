"""OpenAI-backed intent classifiers for the deterministic collection flow."""

from typing import Mapping

from openai import AsyncOpenAI
from pydantic import BaseModel

from common.flows.collection import CollectionIntent, VerifyIntent


class _OpeningIntentClassification(BaseModel):
    intent: CollectionIntent


class _VerifyIntentClassification(BaseModel):
    intent: VerifyIntent


class OpenAIIntentClassifier:
    """Classify caller replies for the opening and verify checkpoints."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def classify_opening(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> CollectionIntent:
        normalized_transcript = transcript.strip()
        if not normalized_transcript:
            raise ValueError("Transcript is empty")

        customer_name = str((state or {}).get("customer_name", "")).strip() or "unknown"
        response = await self._client.responses.parse(
            model=self._model,
            temperature=0,
            max_output_tokens=32,
            instructions=(
                "Classify the reply to a Thai debt-collection opening greeting into exactly one "
                "intent enum. Return only the enum field. "
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
            input=(
                f"customer_name: {customer_name}\n"
                f"user_reply: {normalized_transcript}\n\n"
                "Examples:\n"
                "- 'ครับ พูดอยู่ครับ' => target\n"
                "- 'ตอนนี้ไม่ว่างครับ โทรมาใหม่' => busy\n"
                "- 'เขาไม่อยู่ค่ะ เบอร์นี้เป็นพี่สาว' => other_person\n"
                "- 'leave your message after the tone' => voicemail\n"
                "- 'โทรมาเรื่องอะไรคะ' => faq\n"
                "- 'เอ่อ...' => unknown\n"
            ),
            text_format=_OpeningIntentClassification,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("OpenAI did not return a parsed opening intent")
        return parsed.intent

    async def classify_verify(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> VerifyIntent:
        normalized_transcript = transcript.strip()
        if not normalized_transcript:
            raise ValueError("Transcript is empty")

        state = state or {}
        first_name = str(state.get("first_name", "")).strip() or "unknown"
        lic_no = str(state.get("lic_no", "")).strip() or "unknown"
        province = str(state.get("province", "")).strip() or "unknown"
        response = await self._client.responses.parse(
            model=self._model,
            temperature=0,
            max_output_tokens=32,
            instructions=(
                "Classify the reply to a Thai debt-collection verify question into exactly one "
                "intent enum. Return only the enum field. "
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
            input=(
                f"first_name: {first_name}\n"
                f"lic_no: {lic_no}\n"
                f"province: {province}\n"
                f"user_reply: {normalized_transcript}\n\n"
                "Examples:\n"
                "- 'ใช่ครับ รถผมเอง' => confirmed\n"
                "- 'ตอนนี้ไม่สะดวกคุย โทรมาใหม่ได้ไหม' => target_unavailable\n"
                "- 'ไม่ใช่ค่ะ ฉันเป็นภรรยาเขา' => third_party_speaking\n"
                "- 'โทรมาเรื่องอะไรคะ' => faq\n"
                "- 'เอ่อ...' => unknown\n"
            ),
            text_format=_VerifyIntentClassification,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("OpenAI did not return a parsed verify intent")
        return parsed.intent
