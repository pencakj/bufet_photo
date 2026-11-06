# Krkonoše Live 3.0.1

Eight-camera Krkonoše photo archive with per-location weather, responsive
previews, full-resolution lightbox, themes and dynamically scaled charts.
Production is the **`master` branch**, served on **port 8000** by default.

Repository: https://github.com/pencakj/bufet_photo

## Deploy and run

Use the production checkout `/appl/krkonose_live`:

```sh
docker compose build --pull
docker compose up -d --wait
docker compose logs --tail 50 krkonose_live
```

Open **http://localhost:8000**. The container, Dockerfile, direct Python
entrypoint and health check all use port **8000**. The Compose project and
container are named `krkonose_live`, using image `krkonose_live:3.0.1`.
Health endpoint: `/healthz`.

To refresh dependencies/OS packages, update the appropriate pins, then run:

```sh
docker compose build --pull --no-cache
docker compose up -d --wait
```

## Optional read-only preview

Port **8004** remains available as a read-only viewer of production data:

```sh
docker compose -f docker-compose.preview.yml up -d --wait
docker compose -f docker-compose.preview.yml logs --tail 50 krkonose_live
```

It uses the production image, separate Compose project `krkonose_live_release`
and container `krkonose_live_release`, mapping host 8004 to container 8000.
`READ_ONLY_MODE=true` and `COLLECTORS_ENABLED=false` disable all collection;
every data bind mount is read-only. Weather caches reload when read, so the
viewer follows production updates. Missing display previews fall back to the
original image instead of writing files.

Stop only the viewer with `docker compose -f docker-compose.preview.yml down`.
The old port 8003 deployment has been replaced. The
`release/3.0.0-multicamera` branch/worktree is retained as release history;
**do not run its old collector configuration alongside production**. Manage
both current deployments using the Compose files in this master checkout.

## Storage and collectors

Production owns collection for **all eight cameras** and every weather source.
`LEGACY_READ_ONLY=false`, `WEATHER_POLL_ENABLED=true` and
`COLLECTORS_ENABLED=true` are set in the production Compose file.

| Host directory | Container directory | Purpose |
| --- | --- | --- |
| `/appl/data/bufet/data/images` | `/app/images` | Original camera archive |
| `/appl/data/bufet/data/thumbnails` | `/app/thumbnails` | Original thumbnails |
| `/appl/data/bufet/data/weather` | `/app/data` | Original bufet weather |
| `/appl/data/krkonose_live_release` | `/app/camera-data` | Seven new archives, previews and weather caches |

The last path retains its historical name to preserve all existing captures
without moving or copying data. These directories must be writable by UID/GID
**1001:1001** for production; the viewer mounts the same directories read-only.
Camera archives use `<camera-id>/{images,thumbnails}`; display copies use
`previews/<camera-id>/`, and additional weather caches use `weather/`.
Photo/weather data, credentials and generated reports are excluded from Git.

Capture schedule for all eight cameras: 30 minutes in daylight, 5 minutes for
the first 30 minutes after sunrise and last 30 minutes before sunset, and
once per hour overnight. Solar windows get six captures anchored to their
start; the scheduler wakes at window boundaries rather than sleeping past
them. At most three cameras capture simultaneously. Weather polling remains
every ten minutes, independently of photo collection.
HLS sources are opened only long enough to extract one JPEG frame. No continuous
video is stored. No photo retention/deletion is enabled. Capture and preview
generation pause below 512 MiB free space; monitor archive and cache growth.

## Cameras and weather

| Camera tab | Image source | Weather |
| --- | --- | --- |
| Chalupa na Rozcestí | Original JPEG camera | Bufet / Weathercloud |
| Pec pod Sněžkou | HUMlnet JPEG, Husova bouda | ČHMÚ Pec, 816 m |
| Luční bouda | HUMlnet JPEG | ČHMÚ Luční bouda, 1413 m |
| Sněžka | HUMlnet JPEG | ČHMÚ Poštovna, 1602 m |
| Klínové boudy | Comanet HLS snapshot | Shared bufet weather |
| Svatý Petr – Pláň | Comanet HLS snapshot | Open-Meteo model at 1198 m |
| Bedřichov | Comanet HLS snapshot | Shared ČHMÚ Pec weather |
| Hotel Bedřiška | Comanet HLS snapshot | Shared ČHMÚ Pec weather |

Trusted URLs are in `app/cameras.py`; weather mappings are in
`app/localweather.py`. The provider's Bedřichov page currently publishes a
stream named `Spindl-Stoh`. Attribution links are displayed for every source;
ensure use/redistribution complies with provider terms.

Weather shows its real station, source, time and shared-station/model status.
The Pec camera is at Husova bouda (1046 m), not at the selected valley weather
station (816 m). Open-Meteo is a **model estimate**, not a station observation;
its hosted free API is for non-commercial use subject to provider limits.
ČHMÚ operative ten-minute JSON data carry CC BY 4.0 attribution.

Additional weather sources are fetched once per shared station every ten
minutes and cached for 32 days. ČHMÚ starts with the available recent three
days, then builds longer history; the model provides a lookback, not historical
measurements. Graphs show actual coverage and exclude future forecasts.
Missing sensors are disabled, not shown as zero. Stale data (>2 hours) and
provider errors are labelled. Rain intervals are identified; ČHMÚ/model
pressure is station/surface pressure rather than sea-level pressure.

## Image delivery and API

The main photo uses 640/1280-pixel WebP previews; compact original JPEGs are
served directly if they are smaller. Full resolution loads in the lightbox.
New captures pre-generate display sizes; legacy previews are made on demand
with bounded concurrency and atomic writes. Originals remain unchanged.
Directory timestamps avoid repeatedly rebuilding unchanged archive indexes.
Chart libraries load only when a weather graph is opened.

- `/api/cameras` — cameras, capture state and weather mappings.
- `/api/images?camera=pec&offset=0&limit=50&order=desc` — paginated archive.
- `/images/<filename>?camera=pec` — original JPEG.
- `/thumbnails/<filename>?camera=pec` — gallery thumbnail.
- `/previews/<filename>?camera=pec&width=1280` — display preview (640/1280 only).
- `/api/weather/current?camera=bedriska` — weather and provenance.
- `/api/weather/history?camera=lucni-bouda&hours=24` — history and coverage.

Omitting `camera` selects Chalupa na Rozcestí; unknown IDs return 404.

## Runtime and tests

Python 3.15.2, pinned Python dependencies, minimal checksum-pinned FFmpeg 9.0.2.
Runtime runs non-root with a read-only root filesystem, dropped capabilities,
`no-new-privileges`, and writable data mounts and temporary `/tmp` only.
No build tools or package installer remain in the serving image. Inputs,
paths, JPEGs and resource limits are validated. See `RELEASE_NOTES.md` for
release history; `SECURITY_UPDATE.md` is the historical v2 scan, not a current
security guarantee. Rebuild and rescan as upstream patches become available.

```sh
docker run --rm -v "$PWD/app:/src:ro" -w /src python:3.15.2-slim-trixie \
  sh -c 'pip install -r requirements.txt httpx2 && python -m unittest discover -s tests -v'
npm ci
npm test
npx playwright install chromium
npm run test:browser
```

Browser tests target `http://localhost:8000` by default. Set `APP_URL` to test
the viewer or another deployment. Browser tests require captures for every
camera and reachable weather sources; Python tests use isolated files/mocks.
