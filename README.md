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

## Native combined heating and shaking

The PUDA command `heat_shake(temperature, speed, duration, *, plate_seated,
heatup_timeout=600, speed_timeout=60)` performs one blocking, combined operation.
Durations and timeouts are in seconds. For example, an authorized protocol can
request `temperature=40`, `speed=600`, `duration=300`, `plate_seated=true`.

- The operator must confirm the plate is seated. The command additionally requires
  measured zero RPM, home/locked state, and a closed clamp before setup.
- Temperature must stabilize within **±1°C for 2 seconds** before shaking. The hold
  starts only after measured speed reaches **±2% of target (minimum ±1 RPM)**.
  A still-homed reading just after shaking starts is part of that speed wait.
  Motion reported while the state is still home aborts the operation.
- Fresh temperature, speed, heater, shaker, and clamp readings are checked during
  the operation. Missing/unsafe readings or drift abort the operation; waits for
  heating and speed readiness are bounded.
- Both shaking and temperature control are switched off on success or failure.
  Stopped/home, zero RPM, and heater-off state must be verified within 10 seconds;
  cleanup errors are reported rather than hidden.
- The response reports measured hold duration, temperature/speed extrema and
  shutdown verification. Plate temperature does not establish liquid temperature.
- Keep other robots clear throughout the operation. Use native PUDA validation,
  execution and advertised safety metadata; do not dispatch separate same-machine
  heating and shaking commands concurrently. Legacy `set_temp` and `shake`
  behaviour is unchanged.

Offline verification (no connected device):

```bash
.venv/bin/python -m unittest discover -s tests -v
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
