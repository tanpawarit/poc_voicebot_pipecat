from common.flows.collection import CollectionFlowDefinition, build_collection_flow


def get_flow(name: str, state: dict | None = None) -> CollectionFlowDefinition:
    if name == "collection":
        return build_collection_flow(state or {})
    raise ValueError(f"Unknown flow: {name!r}. Available flows: collection")
