import logging

import uvicorn
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse

from common.config import settings
from common.html import get_html_page
from common.logging import setup_logging
from common.transport import create_connection

logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return get_html_page("Pipecat S2S Bot", settings.flow_name)


@app.post("/api/offer")
async def offer(request: Request, background_tasks: BackgroundTasks) -> dict:
    settings.validate()
    body = await request.json()

    connection = create_connection()
    await connection.initialize(sdp=body["sdp"], type=body["type"])

    from app_s2s.bot import run_bot

    background_tasks.add_task(run_bot, connection)

    return connection.get_answer()


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
