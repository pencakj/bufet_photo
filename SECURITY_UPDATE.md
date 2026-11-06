# Security update — 2026-11-06

Updated and deployed only `krkonose_live` (port 8003). Existing local source
changes and all shared image/weather data were preserved. Other services were
not updated or restarted.

## Runtime and dependencies

- Python 3.12 → 3.15.2, Debian slim trixie, all available Debian package updates.
- FastAPI 0.162.0, Uvicorn 0.54.0, Jinja2 3.1.6, Requests 2.34.2,
  pytz 2026.6, Pillow 13.0.0; Astral 3.2 remains the latest release.
- Transitive Python dependencies resolved fresh at build time.
- Unneeded Uvicorn extras and GLib/JPEG OS dependencies removed. Pillow's
  wheel supplies JPEG support, which was verified.
- pip and its bootstrap bundle removed after installation: neither is needed
  to serve the application. Dependency changes require an image rebuild.
- Chart.js pinned to 4.6.1 and the date adapter to its latest release, 3.0.0,
  with Subresource Integrity checks. The adapter uses its upstream bundled
  date-fns distribution; that embedded library is not separately upgraded.

## Application and container hardening

- Image and thumbnail paths must resolve to JPEG files inside their storage
  directories; traversal and symlink escapes are rejected.
- Pagination and weather ranges validated and bounded.
- Blocking handlers run in FastAPI's thread pool, not on the async event loop.
- Weather errors no longer expose internal exception messages.
- Container runs as storage owner UID/GID 1001, not root; read-only root
  filesystem, temporary `/tmp`, all capabilities dropped, no-new-privileges.
- Health check added. Existing storage ownership was not changed.

## Verification

- 10 automated tests passed, including traversal, symlink escape, input bounds,
  error handling, and current Starlette template compatibility.
- Tests also passed using the non-root, read-only container configuration.
- Live health, homepage, JavaScript, image listing, full JPEG, thumbnail,
  current weather, and weather history returned HTTP 200 after deployment.
- Live traversal returned 404; invalid API ranges returned 422.
- Capture and weather workers successfully wrote to the existing shared data.
- Container reported healthy after deployment.

## Vulnerability scan (Trivy)

Package findings, not a count of independently exploitable application issues:

| Severity | Before | After |
| --- | ---: | ---: |
| Critical | 14 | 0 |
| High | 167 | 49 |
| Medium | 220 | 75 |
| Low | 133 | 62 |
| Unknown | 3 | 0 |

No Python-package findings remain. All 186 remaining findings are Debian
packages with no fixed version available in the scan database. They are not
suppressed. This is not a guarantee that the service has no vulnerabilities;
rebuild and rescan periodically as upstream patches become available.
Host Docker/kernel packages and other services were outside this update's scope.

Scan JSON and test/build logs are in `security-reports/2026-11-06/`.
The pre-update image is retained as
`krkonose_live:pre-security-update-20261106` for rollback. Rolling back also
requires restoring the previous root/writable container settings; do not apply
the new hardening settings blindly to the old image.

To rebuild and redeploy future dependency updates:

```sh
docker compose build --pull --no-cache krkonose_live
docker compose up -d --no-deps --wait krkonose_live
```

Direct dependencies are pinned in `app/requirements.txt`; update those pins
when newer releases are available. Tests are in `app/tests/test_security.py`
and require an external test environment with `httpx2` installed; test tools
are deliberately excluded from the production image.
