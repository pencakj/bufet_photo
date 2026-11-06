# Krkonoše Live

Webcam photo archive and weather dashboard for Pec pod Sněžkou. Built with
FastAPI, Python, and vanilla JavaScript, with lazy-loaded thumbnails, a
day-grouped archive, lightbox, themes, and weather charts.

## Run

The local checkout is `/appl/krkonose_live`. Docker Compose publishes port
**8003** and stores captures and weather outside this repository:

| Host directory | Container directory |
| --- | --- |
| `/appl/data/bufet/data/images` | `/app/images` |
| `/appl/data/bufet/data/thumbnails` | `/app/thumbnails` |
| `/appl/data/bufet/data/weather` | `/app/data` |

These existing directories and weather files must be writable by UID/GID
**1001:1001**. Adjust the bind mounts and runtime user for another machine.
Do not run a second collector against the same storage.

```sh
docker compose build --pull
docker compose up -d --wait
docker compose logs --tail 50 krkonose_live
```

Open `http://localhost:8003`. Health endpoint: `/healthz`.

## Dependencies and security

- Runtime: Python **3.15.2**, Debian trixie slim.
- Direct Python dependencies are pinned in `app/requirements.txt`.
- All **23 installed Python packages**, including transitive dependencies,
  matched the latest PyPI releases when checked on **2026-11-06**.
- Frontend: Chart.js **4.6.1**, date adapter **3.0.0**, pinned with integrity
  checks. The adapter uses its upstream bundled date library, not a separately
  upgraded date-fns release.
- The runtime is non-root with a read-only root filesystem, dropped Linux
  capabilities, and `no-new-privileges`. Only data mounts and `/tmp` are writable.
- Build tooling is removed from the serving image. Rebuild to install updates.

The latest scan found no Python-package vulnerabilities and no critical
findings. Debian still has findings without upstream fixes; this is **not** a
claim that the app is vulnerability-free. See [SECURITY_UPDATE.md](SECURITY_UPDATE.md).

To refresh OS packages and transitive dependencies, rebuild without cache.
Update direct dependency pins and the Python image version when newer
releases become available:

```sh
docker compose build --pull --no-cache krkonose_live
docker compose up -d --no-deps --wait krkonose_live
```

## Tests

Tests use temporary files and mocks, without starting the capture/weather
workers or modifying the archive. From the repository root, use a disposable
development container (no production data mounts):

```sh
docker run --rm -v "$PWD/app:/src:ro" -w /src python:3.15.2-slim-trixie \
  sh -c 'pip install -r requirements.txt httpx2 && python -m unittest discover -s tests -v'
```

Tests and their dependencies are excluded from the production image.

Photo/weather data, credentials, local agent settings, and generated scan
reports are intentionally excluded from Git. This checkout replaces the old
app files while retaining the repository's existing history and `dev` branch.
