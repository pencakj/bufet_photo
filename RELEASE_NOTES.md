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
