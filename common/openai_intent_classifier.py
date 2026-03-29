"""OpenAI-backed stage router for the scripted collection flow."""

from dataclasses import dataclass
from typing import Callable, Mapping, cast

from openai import AsyncOpenAI
from pydantic import create_model

from common.flows.collection import CollectionIntent, CollectionStage, VerifyIntent

StageIntent = CollectionIntent | VerifyIntent


@dataclass(frozen=True)
class _StageClassificationSpec:
    route_enum: type[CollectionIntent] | type[VerifyIntent]
    instructions: str
    build_input: Callable[[str, Mapping[str, object] | None], str]


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


_STAGE_CLASSIFICATION_SPECS: dict[CollectionStage, _StageClassificationSpec] = {
    CollectionStage.OPENING: _StageClassificationSpec(
        route_enum=CollectionIntent,
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
    CollectionStage.VERIFY: _StageClassificationSpec(
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
}


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

    async def classify_stage(
        self,
        stage: CollectionStage,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> StageIntent:
        normalized_transcript = transcript.strip()
        if not normalized_transcript:
            raise ValueError("Transcript is empty")

        spec = _STAGE_CLASSIFICATION_SPECS[stage]
        response_model = create_model(
            f"{stage.value.title()}RouteClassification",
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
            raise ValueError(f"OpenAI did not return a parsed route for stage {stage.value}")

        route = getattr(parsed, "route", None)
        if route is None or not isinstance(route, spec.route_enum):
            raise ValueError(f"OpenAI returned an invalid route for stage {stage.value}")
        return cast(StageIntent, route)

    async def classify_opening(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> CollectionIntent:
        return cast(
            CollectionIntent,
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

    async def classify(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> CollectionIntent:
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
