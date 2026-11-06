# 3.0.1 — Lower-frequency capture schedule

All eight cameras now capture every **30 minutes by day** and **one hour at
night**, with **five-minute** captures in the **30 minutes after sunrise** and
**30 minutes before sunset**. Each solar window has six scheduled shots.
The scheduler wakes at solar window starts even when they fall between regular
hourly/half-hourly ticks; daylight saving and midnight transitions are covered
by regression tests. A capture still occurs once at process startup.

The UI cadence text and deployment image tags are updated. Compression, existing
archives, weather polling (ten minutes), port 8000 and stopped preview state are
unchanged. No photo deletion or recompression is performed.

Verification: 48 Python tests, 2 frontend configuration tests and 3 Chromium
integration tests passed. Live production reports a 3600-second night interval
and its next scheduled capture at 23:00 Europe/Prague after deployment.

---

# 3.0.0 — Production promotion

The multi-camera release is merged into **`master`**. Production now serves
**port 8000**, both on the host and inside image `krkonose_live:3.0.0`.
The previous single-camera service on port 8003 is replaced.

- Production owns all eight camera collectors and all weather polling.
- All existing original and new-camera archives remain in their existing
  directories, without moving, copying or deleting captures.
- Port 8004 remains a read-only viewer using `docker-compose.preview.yml` in
  the master checkout. Its collectors are disabled and all data mounts are
  read-only; it follows production's image and weather updates.
- The historical release branch is preserved. Its old collector configuration
  must not be run alongside production; use the master Compose files instead.
- Dockerfile, direct Python entrypoint, production health checks and browser
  test default all use port 8000.

Promotion verification: 41 Python tests, 2 chart configuration tests and all
3 Chromium integration tests passed against production on port 8000. All eight
cameras completed a fresh capture and bufet weather was saved by production.
Both production and viewer reported healthy; viewer mounts were verified
read-only, with collectors disabled and all camera metadata marked read-only.

The release-candidate notes below describe the earlier rollout and its ports
at that time; the deployment instructions in `README.md` are current.

---

# 3.0.0-rc.3 — Faster image delivery

Release preview remains on **8004**; stable **8003** and `master` are unchanged.
Image tag: `krkonose_live:3.0.0-rc.3`.

- Responsive 640/1280-pixel WebP display previews instead of downloading the
  full JPEG for the main photo. Full-resolution originals remain unchanged and
  are requested for the lightbox. Already compact JPEGs are served directly if
  conversion would increase the transfer size.
- Preview cache lives only in release storage, including previews of the
  read-only original camera. New captures pre-generate display sizes; legacy
  previews are generated on demand with bounded concurrency and atomic writes.
- Directory modification times avoid rebuilding the 109k-photo archive when
  files have not changed. The original index is warmed before serving traffic.
- Chart.js and its date adapter load only when a weather chart is opened,
  retaining version and integrity checks. A blocked chart CDN no longer holds
  up photos; chart loading errors are displayed separately.
- Main image requests have high fetch priority. Mobile selects the smaller
  preview; the original archive and its thumbnails are not rewritten.

Measured in Chromium with a fresh browser context at 1280×900, a simulated
3 Mb/s connection and 80 ms latency: first main photo fully visible in about
**6.7 s before → 1.8 s after** (server preview cache warm). The original camera's
display transfer fell from about **1.8 MB → 195 KB**. JPEG cameras' 1280-pixel
display copies were 89–95% smaller in the live sample. Results depend on the
connection, photo and cache state; first-time preview generation adds work.

Verification: 37 Python tests, 2 chart configuration tests and 3 Chromium
integration tests passed. Tests cover preview dimensions/caching, unchanged
original bytes, invalid paths/sizes, low-disk fallback, unchanged-directory
cache reuse, mobile size selection, full-resolution lightbox and photos loading
with the chart CDN blocked. All eight cameras' previews were checked not to
exceed their original JPEG transfer size. Both containers remained healthy.

---

# 3.0.0-rc.2 — Per-camera weather

Release branch remains `release/3.0.0-multicamera`. The preview container now
uses image `krkonose_live:3.0.0-rc.2` on host port **8004**; stable **8003** and
`master` are unchanged.

- Bedřichov and Hotel Bedřiška share ČHMÚ Pec pod Sněžkou weather.
- Klínové boudy shares the existing bufet / Chalupa na Rozcestí weather.
- Luční bouda and Sněžka use their own ČHMÚ observations.
- Svatý Petr – Pláň uses an explicitly labelled Open-Meteo model estimate.
- Weather chip and charts follow the selected camera, with source/station,
  observation time, shared-station notes, stale/error states and real coverage.
- Missing sensors are disabled, not fabricated as zeros. Rain intervals and
  station pressure are identified. Older camera/range requests cannot overwrite
  a newer selection.
- New weather caches are stored only in the release data directory and shared
  between cameras using the same station. Production weather remains read-only.
- Verified live responses for all eight camera mappings; 31 Python tests,
  2 frontend configuration tests and 2 Chromium integration tests passed.

The original rc.1 release notes below are retained as a historical record.

---

# 3.0.0-rc.1 — Multi-camera preview

Release branch: `release/3.0.0-multicamera`.
Stable `master` remains at `e59808f` (the deployed v2 with dynamic temperature
scaling). Existing `dev` history has not been rewritten.

## What's new

- Eight top-level camera tabs, original Chalupa na Rozcestí first.
- Seven additional independent archives: Pec pod Sněžkou, Luční bouda,
  Sněžka, Klínové boudy, Svatý Petr – Pláň, Bedřichov and Hotel Bedřiška.
- JPEG downloads and one-frame HLS video snapshots using minimal FFmpeg 9.0.2.
- Per-camera latest capture, source attribution, status, totals, and full-day
  Prague-time counts. Sorting, themes, lightbox and temperature auto-scaling retained.
- Aborted/stale responses cannot mix images when switching tabs or sorting.
- Keyboard-accessible, horizontally scrollable tabs; mobile layout verified.
- At most three concurrent captures, bounded network/process operations,
  full JPEG decoding before archive publication, one retry for torn JPEGs,
  atomic writes and low-disk capture suspension. Existing snapshots are not deleted.

## Deployment

| | Stable | Preview |
| --- | --- | --- |
| Directory | `/appl/krkonose_live` | `/appl/krkonose_live_release` |
| Branch | `master` | `release/3.0.0-multicamera` |
| Container | `krkonose_live` | `krkonose_live_release` |
| Image | `krkonose_live:2.0` | `krkonose_live:3.0.0-rc.1` |
| Host port | **8003** | **8004** |

Production stayed running throughout preview development. The preview's original
archive, thumbnails and weather mounts are read-only; only production polls
the original camera/station. New camera data lives separately under
`/appl/data/krkonose_live_release`. See `README.md` for management commands.

## Verification — 2026-11-06

- 20 Python tests passed in the non-root, read-only runtime configuration.
- 2 frontend configuration tests passed.
- Chromium integration test passed: eight tabs, every camera's full image and
  lightbox, rapid switching, sorting, themes, actual chart bounds, keyboard
  navigation and mobile page width. No uncaught browser errors.
- Actual minimal-FFmpeg snapshots decoded successfully from all four HLS
  sources (three 1280×720, Bedřichov 1920×1080).
- Both deployments reported healthy; all eight latest images and thumbnails
  returned HTTP 200. Each new camera completed a capture on the final build.
- npm audit: no findings in the development test dependencies.
- Trivy: no Python-package findings, no critical findings, no findings with
  available fixes. Remaining Debian findings: **49 high, 75 medium, 62 low**.
  These are not suppressed. A dependency scan is not a complete security audit,
  including of the custom-built FFmpeg binary.

Raw scan JSON and build/test logs are stored locally in ignored
`security-reports/2026-11-06/`, not published with source or media.

## Operational notes

- Storage grows with seven additional cameras; no retention policy is enabled.
  New collection pauses below 512 MiB free, without deleting any archived data.
- Weather always refers to Chalupa na Rozcestí, not measurements at each camera.
- Stream URLs can change or go offline; failures are isolated per camera and
  retried on the next scheduled cycle. Source URLs remain server-controlled.
- The provider's Bedřichov page currently publishes `Spindl-Stoh.stream`.
- This is a separate release candidate, not a production replacement. Stopping
  preview with `docker compose down` in its checkout leaves stable untouched.
