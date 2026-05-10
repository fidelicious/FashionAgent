"""
Clawbot entry point — foundation pass stub.

The real Discord bot, FastAPI server, and image worker are wired up in
upcoming build steps. This stub keeps the container alive so the build
plumbing can be verified without crash-looping.
"""

import logging
import signal
import time

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Clawbot starting (foundation-pass stub) — waiting for build steps to land.")

    # Block until SIGTERM/SIGINT (sent by Docker on container stop).
    stop = False

    def _handle_signal(sig, frame):  # noqa: ANN001
        nonlocal stop
        logger.info("Received signal %s, shutting down.", sig)
        stop = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not stop:
        time.sleep(1)

    logger.info("Clawbot stopped.")


if __name__ == "__main__":
    main()
