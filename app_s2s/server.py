import logging
from typing import Literal

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from common.config import settings
from common.html import get_html_page
from common.logging import setup_logging
from common.transport import create_connection

logger = logging.getLogger(__name__)

app = FastAPI()


class OfferRequest(BaseModel):
    sdp: str
    type: Literal["offer"]


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return get_html_page("Pipecat S2S Bot", settings.flow_name)


@app.post("/api/offer")
async def offer(body: OfferRequest, background_tasks: BackgroundTasks) -> dict:
    settings.validate()

    connection = create_connection()
    try:
        await connection.initialize(sdp=body.sdp, type=body.type)
    except Exception as exc:
        logger.warning("Invalid WebRTC offer payload", exc_info=exc)
        raise HTTPException(status_code=400, detail="Invalid WebRTC offer") from exc

    from app_s2s.bot import run_bot

    answer = connection.get_answer()
    if not answer:
        raise HTTPException(status_code=502, detail="Failed to initialize WebRTC session")

    background_tasks.add_task(run_bot, connection)
    return answer


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


def main() -> None:
    setup_logging()
    logger.info(
        "Starting S2S server",
        extra={"event": "server_start", "host": settings.host, "port": settings.s2s_port},
    )
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.s2s_port,
        ssl_certfile="certs/cert.pem",
        ssl_keyfile="certs/key.pem",
    )


if __name__ == "__main__":
    main()
