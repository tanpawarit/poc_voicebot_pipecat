import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    openai_base_url: str | None = field(
        default_factory=lambda: os.environ.get("OPENAI_BASE_URL") or None
    )
    openai_stt_model: str = field(
        default_factory=lambda: os.environ.get("OPENAI_STT_MODEL", "gpt-4o-transcribe")
    )
    openai_intent_model: str = field(
        default_factory=lambda: os.environ.get("OPENAI_INTENT_MODEL", "gpt-4o-mini")
    )
    openai_tts_model: str = field(
        default_factory=lambda: os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    )
    openai_tts_voice: str = field(
        default_factory=lambda: os.environ.get("OPENAI_TTS_VOICE", "coral")
    )
    openai_tts_speed: float = field(
        default_factory=lambda: float(os.environ.get("OPENAI_TTS_SPEED", "1.2"))
    )
    openai_tts_instructions: str = field(
        default_factory=lambda: os.environ.get(
            "OPENAI_TTS_INSTRUCTIONS",
            (
                "Speak in natural Thai with a warm, human customer-service tone. "
                "Use smooth pacing, gentle prosody, and short natural pauses. "
                "Avoid robotic cadence, flat delivery, and over-enunciation."
            ),
        )
    )
    flow_name: str = field(default_factory=lambda: os.environ.get("FLOW", "collection"))
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    cascaded_port: int = field(default_factory=lambda: int(os.environ.get("CASCADED_PORT", "7860")))
    s2s_port: int = field(default_factory=lambda: int(os.environ.get("S2S_PORT", "7861")))
    vad_stop_secs: float = field(
        default_factory=lambda: float(os.environ.get("VAD_STOP_SECS", "0.2"))
    )
    turn_end_timeout_secs: float = field(
        default_factory=lambda: float(os.environ.get("TURN_END_TIMEOUT_SECS", "2.0"))
    )

    def validate(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError(
                "Missing required environment variable: OPENAI_API_KEY. "
                "Copy .env.example to .env and fill in your key."
            )
        if self.vad_stop_secs <= 0:
            raise RuntimeError("VAD_STOP_SECS must be > 0")
        if self.turn_end_timeout_secs <= 0:
            raise RuntimeError("TURN_END_TIMEOUT_SECS must be > 0")
        if self.openai_tts_speed <= 0:
            raise RuntimeError("OPENAI_TTS_SPEED must be > 0")


settings = Settings()
