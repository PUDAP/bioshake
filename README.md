# bioshake

BioShake driver and edge service.

## What It Does

- Runs the bioshake machine edge service.
- Connects to NATS and translates commands into machine actions.
- Communicates with the bioshake device over serial.

## Prerequisites

- Docker and Docker Compose installed
- Python 3.14+ and `uv` (for baremetal mode)
- bioshake device reachable on the serial port

## Environment Setup

From repo root:

```bash
cp .env.example .env
```

Edit `.env` and configure:

- `MACHINE_ID`
- `NATS_SERVERS`
- `BIOSHAKE_HOST_PORT` — serial-device path on the Docker host
- `BIOSHAKE_PORT` — serial-device path exposed inside the container

The example uses `/dev/ttyUSB0` for both paths. Prefer a stable
`/dev/serial/by-id/...` value for `BIOSHAKE_HOST_PORT` in production. Docker
device mappings require Linux device paths; Windows `COM` names are supported
only in bare-metal mode.

## Run With Docker (Recommended)

All commands below are run from repo root.

Build and start:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f
```

Stop:

```bash
docker compose down
```

## Run Baremetal (uv)

From repo root:

```bash
uv sync
uv run python main.py
```

## Build and Push Image (GHCR)

Login:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

Build:

```bash
docker compose build
```

Push:

```bash
docker push ghcr.io/PUDAP/bioshake-edge:latest
```

Or with Compose:

```bash
docker compose push
```
