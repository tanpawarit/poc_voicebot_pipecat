from pipecat_flows import NodeConfig


def get_flow(name: str, state: dict | None = None) -> NodeConfig:
    if name == "collection":
        from common.flows.collection import create_initial_node
        return create_initial_node(state or {})
    raise ValueError(f"Unknown flow: {name!r}. Available flows: collection")
