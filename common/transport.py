from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

ICE_SERVERS = ["stun:stun.l.google.com:19302"]


def create_connection() -> SmallWebRTCConnection:
    return SmallWebRTCConnection(ice_servers=ICE_SERVERS)


def create_transport(connection: SmallWebRTCConnection) -> SmallWebRTCTransport:
    return SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )
