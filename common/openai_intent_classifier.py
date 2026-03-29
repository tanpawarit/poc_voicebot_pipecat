"""OpenAI-backed intent classifier for the deterministic collection flow."""

from typing import Mapping

from openai import AsyncOpenAI
from pydantic import BaseModel

from common.flows.collection import CollectionIntent


class _IntentClassification(BaseModel):
    intent: CollectionIntent


class OpenAIIntentClassifier:
    """Classify the caller's reply after the opening greeting."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def classify(
        self,
        transcript: str,
        state: Mapping[str, object] | None = None,
    ) -> CollectionIntent:
        normalized_transcript = transcript.strip()
        if not normalized_transcript:
            raise ValueError("Transcript is empty")

        customer_name = str((state or {}).get("customer_name", "")).strip()
        response = await self._client.responses.parse(
            model=self._model,
            temperature=0,
            max_output_tokens=32,
            instructions=(
                "Classify the reply to a Thai debt-collection opening line into exactly one "
                "intent enum. Return only the enum field. "
                "Use 'target' when the speaker confirms they are the requested person, or "
                "replies in a way that implies the requested person is speaking. "
                "Use 'busy' when the requested person is on the line but unavailable, asks "
                "for a callback, or says they are not free to talk. "
                "Use 'other_person' when someone else answers and indicates the requested "
                "person is unavailable, absent, or not the one speaking. "
                "Use 'voicemail' when the transcript sounds like an answering machine, "
                "automated greeting, voicemail prompt, or instruction to leave a message."
            ),
            input=(
                f"customer_name: {customer_name or 'unknown'}\n"
                f"user_reply: {normalized_transcript}\n\n"
                "Examples:\n"
                "- 'ค่ะ พูดอยู่ค่ะ' => target\n"
                "- 'ไม่ว่างครับ โทรมาใหม่' => busy\n"
                "- 'เขาไม่อยู่ ฝากบอกได้ไหม' => other_person\n"
                "- 'leave a message after the tone' => voicemail\n"
            ),
            text_format=_IntentClassification,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("OpenAI did not return a parsed intent")
        return parsed.intent
