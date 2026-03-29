import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    gemini_api_key: str = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY", "")
    )
    gemini_live_model: str = field(
        default_factory=lambda: os.environ.get(
            "GEMINI_LIVE_MODEL",
            "gemini-3.1-flash-live-preview",
        )
    )
    gemini_live_voice: str = field(
        default_factory=lambda: os.environ.get("GEMINI_LIVE_VOICE", "Aoede")
    )
    flow_name: str = field(default_factory=lambda: os.environ.get("FLOW", "collection"))
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    s2s_port: int = field(default_factory=lambda: int(os.environ.get("S2S_PORT", "7861")))

    def validate(self) -> None:
        if not self.gemini_api_key:
            raise RuntimeError(
                "Missing required environment variable: GEMINI_API_KEY or GOOGLE_API_KEY. "
                "Copy .env.example to .env and fill in your key."
            )


settings = Settings()
