from common.flows.collection import (
    CollectionFlowDefinition,
    build_collection_flow,
    build_collection_gemini_system_instruction,
)


def get_flow(name: str, state: dict | None = None) -> CollectionFlowDefinition:
    if name == "collection":
        return build_collection_flow(state or {})
    raise ValueError(f"Unknown flow: {name!r}. Available flows: collection")


def get_gemini_live_system_instruction(name: str, state: dict | None = None) -> str:
    if name == "collection":
        return build_collection_gemini_system_instruction(state or {})
    raise ValueError(f"Unknown flow: {name!r}. Available flows: collection")
