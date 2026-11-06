# Krkonoše Live — multi-camera release candidate

Photo archives for eight Krkonoše webcams. The first tab is the existing
Chalupa na Rozcestí camera; the remaining seven tabs have independent archives.
The interface retains sorting, lazy thumbnails, lightbox, themes, and
automatically scaled temperature charts.

## Deployment layout

| Version | Git branch | Checkout | Container | Host port |
| --- | --- | --- | --- | --- |
| Stable | `master` | `/appl/krkonose_live` | `krkonose_live` | **8003** |
| Preview | `release/3.0.0-multicamera` | `/appl/krkonose_live_release` | `krkonose_live_release` | **8004** |

Both branches are in https://github.com/pencakj/bufet_photo. The preview does
not replace or restart stable. Each checkout has a separate Compose project
and image tag. Run commands in the matching checkout.

## Cameras

| Tab | Provider | Capture |
| --- | --- | --- |
| Chalupa na Rozcestí | Chalupa na Rozcestí | Existing production archive, read-only |
| Pec pod Sněžkou | HUMlnet | JPEG |
| Luční bouda | HUMlnet | JPEG |
| Sněžka | HUMlnet | JPEG |
| Klínové boudy | Comanet / Webkamery Krkonoše | HLS → JPEG |
| Svatý Petr – Pláň | Comanet / Webkamery Krkonoše | HLS → JPEG |
| Bedřichov | Comanet / Webkamery Krkonoše | HLS → JPEG |
| Hotel Bedřiška | Comanet / Webkamery Krkonoše | HLS → JPEG |

Trusted URLs and display names live in `app/cameras.py`. The provider's
Bedřichov page currently references a stream named `Spindl-Stoh`; the app
uses that page's published stream rather than guessing a different endpoint.
Source attribution links are shown for each tab. Ensure your use and
redistribution comply with the providers' terms.

New cameras use the existing regional schedule: 10 minutes in daylight,
2 minutes near sunrise/sunset during daylight, 30 minutes overnight.
At most three captures run simultaneously. Videos are opened only long enough
to extract one JPEG frame; continuous video is neither stored nor relayed.

## Storage and isolation

The preview mounts these original production directories **read-only**:

- `/appl/data/bufet/data/images` → `/app/images`
- `/appl/data/bufet/data/thumbnails` → `/app/thumbnails`
- `/appl/data/bufet/data/weather` → `/app/data`

Only stable captures the original camera and polls its Weathercloud station.
`LEGACY_READ_ONLY=true` and `WEATHER_POLL_ENABLED=false` enforce that in preview.
The preview independently polls the additional weather sources listed below,
without writing to the original Weathercloud archive.

### Weather per camera (3.0.0-rc.2)

| Camera | Weather source |
| --- | --- |
| Chalupa na Rozcestí | Existing bufet / Weathercloud station, read-only |
| Klínové boudy | Same bufet station, explicitly marked shared |
| Pec pod Sněžkou | ČHMÚ Pec pod Sněžkou, 816 m |
| Bedřichov | Same ČHMÚ Pec station, explicitly marked shared |
| Hotel Bedřiška | Same ČHMÚ Pec station, explicitly marked shared |
| Luční bouda | ČHMÚ Luční bouda, 1413 m |
| Sněžka | ČHMÚ Sněžka, Poštovna, 1602 m |
| Svatý Petr – Pláň | Open-Meteo model for the camera coordinates at 1198 m, **not a station observation** |

The Pec camera is at Husova bouda (1046 m), while the chosen ČHMÚ station is
in the valley (816 m); the interface explicitly states this difference.
ČHMÚ operative ten-minute JSON data are used with CC BY 4.0 attribution.
Open-Meteo supplies hourly model values with wind speed requested in m/s;
its hosted free API is for non-commercial use, subject to provider limits.

Weather is requested server-side once per shared station every ten minutes,
not once per camera or browser. The additional station caches live under
`/appl/data/krkonose_live_release/weather`, persist across restarts, and retain
32 days. ČHMÚ bootstraps the available recent three days; older graph ranges
fill as collection continues. Open-Meteo provides a model lookback, not
historical measurements. Every graph shows the actual available date range.
Future forecasts are excluded from history. Original weather history is neither
copied nor modified.

The interface shows the actual station, measurement/model distinction,
observation time, provider errors and a warning for data older than two hours.
Unavailable sensors are disabled rather than shown as zero. Rain charts state
the source interval (ten minutes for ČHMÚ, one hour for the model); bufet rain
retains its original station-counter semantics. Pressure from ČHMÚ/model is
station/surface pressure, not sea-level pressure.

New snapshots are stored under
`/appl/data/krkonose_live_release/<camera-id>/{images,thumbnails}`. This root
must be writable by UID/GID **1001:1001**. Original files are not moved or
renamed. No automatic retention/deletion is enabled. Captures pause below
512 MiB free space; monitor usage and agree a retention policy before the
archive fills the disk. Photos, weather records and generated reports stay
outside Git.

## Run preview

```sh
cd /appl/krkonose_live_release
docker compose build --pull
docker compose up -d --wait
docker compose logs --tail 50 krkonose_live
```

Visit `http://localhost:8004`. Health: `/healthz`. Camera/status registry:
`/api/cameras`. Archive: `/api/images?camera=pec&offset=0&limit=50&order=desc`.
Images, thumbnails and thumbnail generation accept the same `camera` parameter;
omitting it selects the original camera. Unknown camera IDs return 404.
Weather endpoints also accept `camera`, for example
`/api/weather/current?camera=bedriska` and
`/api/weather/history?camera=lucni-bouda&hours=24`. Responses include source
metadata; history also includes actual coverage timestamps.

To stop **only** preview, run `docker compose down` in this checkout. It does
not delete bind-mounted archives. Do not run stable's commands from this directory.

## Runtime and security

- Python 3.15.2; direct dependencies pinned in `app/requirements.txt`.
- Minimal FFmpeg **9.0.2** built from checksum-pinned upstream source in a
  separate build stage. Only HLS/HTTPS, required video decoding, scaling and
  JPEG encoding are enabled. Source URL, checksum and configure flags are in
  `app/Dockerfile`; LGPLv3 licence is included in the image.
- No build tools or package installer in the runtime. No public arbitrary-URL
  capture endpoint, shell execution, or unbounded continuous recording.
- Non-root container, read-only root filesystem, temporary `/tmp`, dropped
  capabilities and `no-new-privileges`.
- JPEG verification, download/process limits, atomic writes, camera-scoped
  caches, path-containment checks, and bounded API inputs.
- Chart.js and its date adapter remain version/integrity pinned.

`SECURITY_UPDATE.md` records the historical **stable v2** scan; it is not the
scan for this release candidate. Rebuild/rescan periodically; unpatched OS
findings can remain even after all available updates.

## Tests

Python tests require no camera access or production mounts:

```sh
docker run --rm -v "$PWD/app:/src:ro" -w /src python:3.15.2-slim-trixie \
  sh -c 'pip install -r requirements.txt httpx2 && python -m unittest discover -s tests -v'
```

Frontend tests use Node.js; browser tests exercise a running preview with
captures available for every camera:

```sh
npm ci
npm test
npx playwright install chromium
npm run test:browser
```

Set `APP_URL` to override the browser test's default `http://localhost:8004`.
Tests cover camera order/isolation, JPEG/video capture, read-only originals,
storage protection, traversal, inputs, tab switching/races, keyboard/mobile
navigation, lightbox, sorting, weather charts and dynamic temperature bounds.
