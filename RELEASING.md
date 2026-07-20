# Maintaining and releasing

How to change the program, push updates to GitHub, and publish a new release
with the Windows `.exe`. Written so you can follow it months from now without
remembering anything.

The GitHub repository is <https://github.com/brianhaupt/pota-accessible>.

---

## One-time setup

You only need these installed once:

- **Python 3.8+** — <https://www.python.org/downloads/>
- **PyInstaller** (to build the `.exe`):
  ```powershell
  py -m pip install -r requirements-dev.txt
  ```
- **Git**, already configured and authenticated to GitHub (you pushed the repo,
  so this is done).

---

## Everyday: make and test a change

1. Edit `pota_accessible.py`.
2. Run it and check it in a browser:
   ```powershell
   python pota_accessible.py
   ```
   Close the browser window to stop it. Confirm your change works and that
   marking/unmarking spots, filters, search, and refresh all still behave.
3. Commit and push the change (no release needed for day-to-day work):
   ```powershell
   git add -A
   git commit -m "Describe what changed"
   git push
   ```

That updates the code on GitHub. The README's download link always points to
the **latest release**, so pushing code does not change what users download
until you cut a new release (below).

---

## Cutting a new release (with a new `.exe`)

A release is a tagged snapshot (e.g. `v1.1.0`) plus the built `.exe` attached
so people can download it.

### Version numbers

The version lives in **one place**: `__version__` near the top of
`pota_accessible.py`. It shows in the page footer and via
`python pota_accessible.py --version`.

Bump it using [semantic versioning](https://semver.org/):

| Change                                   | Bump          | Example         |
| ---------------------------------------- | ------------- | --------------- |
| Bug fix, small tweak                     | patch         | 1.0.0 → 1.0.1   |
| New feature, backward-compatible         | minor         | 1.0.1 → 1.1.0   |
| Breaking change / big rework             | major         | 1.1.0 → 2.0.0   |

### The fast way (recommended): `release.ps1`

1. Bump `__version__` in `pota_accessible.py`.
2. Commit everything:
   ```powershell
   git add -A
   git commit -m "Release vX.Y.Z"
   ```
3. Run the release script from this folder:
   ```powershell
   ./release.ps1
   ```
   If PowerShell blocks it:
   ```powershell
   powershell -ExecutionPolicy Bypass -File release.ps1
   ```

The script reads the version from the source, refuses to run if you have
uncommitted changes or if the tag already exists, builds the `.exe`, creates
and pushes the `vX.Y.Z` tag, and opens the GitHub "new release" page with the
tag pre-filled.

4. In the browser page that opens: **attach**
   `dist\POTA-Accessible-Spots.exe`, add a short description, and click
   **Publish release**.

Done. The download link in the README now serves the new `.exe`.

### The manual way (no script)

If you'd rather do each step yourself:

1. Bump `__version__`, then commit and push:
   ```powershell
   git add -A
   git commit -m "Release vX.Y.Z"
   git push
   ```
2. Build the executable:
   ```powershell
   build.bat
   ```
   (or `py -m PyInstaller --onefile --windowed --name "POTA-Accessible-Spots" --distpath dist --workpath build --specpath build pota_accessible.py`)
3. Optionally smoke-test it:
   ```powershell
   dist\POTA-Accessible-Spots.exe --version
   dist\POTA-Accessible-Spots.exe        # opens the browser; close to quit
   ```
4. Tag and push the tag:
   ```powershell
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```
5. Go to
   <https://github.com/brianhaupt/pota-accessible/releases/new>, choose the
   `vX.Y.Z` tag, attach `dist\POTA-Accessible-Spots.exe`, write notes, and
   **Publish release**.

---

## Notes and gotchas

- **The `.exe` is never committed to git.** It's a build output (ignored via
  `.gitignore`); it only lives on the Releases page. Same for `worked_log.json`
  (personal data) and the `build/` and `dist/` folders.
- **SmartScreen.** The `.exe` is unsigned, so downloaders may see "Windows
  protected your PC" → **More info → Run anyway**. Removing this requires a
  code-signing certificate.
- **macOS/Linux users** run from source (`python3 pota_accessible.py`); there
  is no binary for them, by design. See the README.
- **Rebuilding the current release's binary?** If you ever need to replace the
  `.exe` on an existing release without bumping the version, build it and use
  the release's "Edit" page to re-upload the asset. Prefer bumping the patch
  version instead, so versions and binaries stay in lock-step.
- **Verify a build's version:** `dist\POTA-Accessible-Spots.exe --version`
  should match the tag you're releasing.
