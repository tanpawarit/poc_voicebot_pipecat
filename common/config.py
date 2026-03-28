import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    google_api_key: str = field(default_factory=lambda: os.environ.get("GOOGLE_API_KEY", ""))
    flow_name: str = field(default_factory=lambda: os.environ.get("FLOW", "collection"))
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    cascaded_port: int = field(default_factory=lambda: int(os.environ.get("CASCADED_PORT", "7860")))
    s2s_port: int = field(default_factory=lambda: int(os.environ.get("S2S_PORT", "7861")))

    def validate(self) -> None:
        if not self.google_api_key:
            raise RuntimeError(
                "Missing required environment variable: GOOGLE_API_KEY. "
                "Copy .env.example to .env and fill in your key."
            )


settings = Settings()
