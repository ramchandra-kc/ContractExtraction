"""``contract-gateway``: serve the gateway on GATEWAY__HOST:GATEWAY__PORT."""

from __future__ import annotations

import logging


def main() -> None:
    import uvicorn

    from .app import create_app
    from .settings import load_settings

    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    uvicorn.run(
        create_app(settings), host=settings.gateway.host, port=settings.gateway.port, log_config=None,
        access_log=False,      # the app writes one access line per request, with its request id
        proxy_headers=False,   # the gateway is the edge: never trust client-sent X-Forwarded-* for the peer address
        server_header=False,
    )


if __name__ == "__main__":
    main()
