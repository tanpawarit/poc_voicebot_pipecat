from common.flows.collection import (
    build_collection_gemini_initial_messages,
    build_collection_gemini_system_instruction,
)

def get_gemini_live_system_instruction(name: str, state: dict | None = None) -> str:
    if name == "collection":
        return build_collection_gemini_system_instruction(state or {})
    raise ValueError(f"Unknown flow: {name!r}. Available flows: collection")


def get_gemini_live_initial_messages(name: str, state: dict | None = None) -> list[dict[str, str]]:
    if name == "collection":
        return build_collection_gemini_initial_messages(state or {})
    raise ValueError(f"Unknown flow: {name!r}. Available flows: collection")
