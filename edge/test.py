from __future__ import annotations

import time
import logging

from centrifuge import Centrifuge

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logging.getLogger("centrifuge").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

WS_URL = "ws://192.168.2.102:81"


def run_sequence(device: str) -> None:
    centri = Centrifuge(ws_url=WS_URL)

    try:
        centri.startup()
        centri.get_mac_address()
        centri.get_position()

        centri.open_lid(device)
        centri.close_lid(device)

        centri.spin(device, duration=3)
    finally:
        centri.close()


if __name__ == "__main__":
    run_sequence("2")
    # Uncomment if you also want to run device 2:
    # run_sequence("2")
