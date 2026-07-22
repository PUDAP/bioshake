"""
Main entry point for the BioShake machine edge service.

This module provides the main event loop for the BioShake machine, handling command
execution via NATS messaging, telemetry publishing, and connection management.
"""
import asyncio
import logging
import sys
import time
import psutil
from pydantic_settings import BaseSettings, SettingsConfigDict
from puda import EdgeNatsClient, EdgeRunner
from bioshake_driver import BioShake


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)
logging.getLogger("bioshake_driver").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Environment configuration
class Config(BaseSettings):
    machine_id: str
    nats_servers: str
    bioshake_port: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def nats_server_list(self) -> list[str]:
        return [s.strip() for s in self.nats_servers.split(",") if s.strip()]

def load_config() -> Config:
    """Load and validate configuration; exit process on failure."""
    try:
        return Config()
    except Exception as e:
        logger.error("Failed to load configuration: %s", e, exc_info=True)
        sys.exit(1)


async def main():
    """Initialize the BioShake machine driver and NATS client, then run the edge runner."""
    config = load_config()
    logger.info("Config loaded for %s", config.machine_id)
    logger.info("Full config: %s", config.model_dump())

    logger.info("Initializing machine driver")
    driver = BioShake(port=str(config.bioshake_port))
    logger.info("BioShake machine initialized successfully")

    logger.info("Connecting to NATS at %s", config.nats_servers)
    edge_nats_client = EdgeNatsClient(
        servers=config.nats_server_list,
        machine_id=config.machine_id,
    )

    async def telemetry_handler():
        await edge_nats_client.publish_heartbeat()
        await edge_nats_client.publish_position(driver.get_position())
        all_temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
        sensor = next((v[0] for k in ("coretemp", "cpu_thermal", "k10temp", "acpitz") if (v := all_temps.get(k))), None)
        await edge_nats_client.publish_health({
            "cpu": psutil.cpu_percent(interval=None),
            "mem": psutil.virtual_memory().percent,
            "temp": sensor.current if sensor else None,
        })

    runner = EdgeRunner(
        nats_client=edge_nats_client,
        machine_driver=driver,
        telemetry_handler=telemetry_handler,
        state_handler=lambda: {},
    )
    await runner.connect()
    logger.info("NATS client initialized successfully")
    logger.info(
        "==================== %s Edge Service Ready. Publishing telemetry... ====================",
        config.machine_id,
    )
    await runner.run()


# Run main in a loop; retry on fatal errors, ignore KeyboardInterrupt.
if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.warning("Received KeyboardInterrupt, but continuing to run...")
            time.sleep(1)
        except Exception as e:
            logger.error("Fatal error: %s", e, exc_info=True)
            time.sleep(5)
