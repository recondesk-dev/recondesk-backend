# ReconDesk Tally Bridge (local agent)

Local Windows agent that exports **Bills Payable** (unpaid only) and **Day Book Payment Agst Ref** rows from Tally and pushes them to ReconDesk. Auto-settle happens only from Payment Agst Ref when party-name confidence clears the server gate.

## For CAs (no Python required)

1. In ReconDesk → Settings → Tally Bridge, generate an API key.
2. Download **Windows agent (.exe)** and the config example.
3. Rename the config to `tally_bridge.config.json`, put it **next to** `ReconDeskTallyBridge.exe`, and paste your API key / company name.
4. Open Tally, load the company, enable the XML server (F1 → Settings → Connectivity).
5. Test first:

```text
ReconDeskTallyBridge.exe --config tally_bridge.config.json --test
```

Confirm both exports print non-zero row counts (or investigate empty exports before enabling push).

6. Run once or leave on a timer:

```text
ReconDeskTallyBridge.exe --config tally_bridge.config.json --once
ReconDeskTallyBridge.exe --config tally_bridge.config.json
```

Unsigned builds may trigger Windows SmartScreen on first run — use “More info → Run anyway” after verifying the download source.

## For maintainers (build the .exe)

Requires **Windows** (or GitHub Actions `windows-latest`). PyInstaller does not cross-compile a Win32 binary from macOS/Linux.

```powershell
cd recondesk-backend\tally_bridge
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Output: `dist\ReconDeskTallyBridge.exe`

CI: `.github/workflows/build-tally-bridge.yml` builds on push/PR touching this folder and uploads the artifact. Tags matching `tally-bridge-v*` also publish a GitHub Release asset.

### Serving the download

- Drop the built exe into `tally_bridge/dist/ReconDeskTallyBridge.exe` on the API host, **or**
- Set backend env `TALLY_BRIDGE_EXE_URL` to the Release/CDN URL.

`GET /api/tally-sync/agent-exe` serves the local file if present, otherwise redirects to that URL.
