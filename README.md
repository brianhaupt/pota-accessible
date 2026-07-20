# POTA Accessible Spots

An accessible viewer for the live [Parks on the Air](https://pota.app/) (POTA)
activator spots feed, built for use with screen readers such as **JAWS**, NVDA,
and VoiceOver.

The official spots page presents each spot as a list of unlabeled values with
no table headers, several unlabeled icon buttons, and a 60-second auto-refresh
that moves a screen reader's reading position without warning. This viewer
presents the same live data as a proper, semantic, keyboard-friendly web page —
so a blind operator can read and work spots efficiently.

It runs as a tiny local web app: a small Python program fetches the data and
serves a clean page to your browser. Nothing is installed system-wide, and no
data leaves your machine except the read-only request to POTA's public API.

![Screenshot of POTA Accessible Spots: a page titled "POTA Active Spots" with
labeled Search, Band, Mode, Program, and Sort controls, a status line reading
"Updated at 12:47:40 PM. 72 spots.", and a data table with columns for Age,
Callsign, Frequency, Band, Mode, Park, Location, Spotter, Comment, and a "Mark
worked" button on each row.](docs/screenshot.png)

---

## Features

- **Real data table** with proper column headers (`Age`, `Callsign`,
  `Frequency`, `Band`, `Mode`, `Park`, `Location`, `Spotter`, `Comment`,
  `Action`). A screen reader announces the column name before each value, and
  repeats the activator callsign as a row header while you move across a row.
- **Labeled filters and search** — free-text search plus Band, Mode, and
  Program/entity dropdowns, a sort selector, and a "Hide QRT (finished) spots"
  toggle. Every control has a real `<label>`.
- **Mark contacts as worked** — one button per spot removes it from the list
  once you've made the contact, and logs it. See
  [How "worked" tracking works](#how-worked-tracking-works).
- **Manual refresh** — the list updates only when you press *Refresh spots*, so
  your reading position is never pulled out from under you. A polite live region
  announces the result count without stealing keyboard focus.
- **Auto-close** — when you close the browser window, the background program
  shuts itself down within a few seconds.
- **Light and dark themes**, a "skip to table" link, and strong keyboard focus
  indicators.

---

## Requirements

- **Python 3.8 or newer** (standard library only — no third-party packages to
  install to run it).
- An internet connection (to reach the POTA API).
- **Any OS** — Windows, macOS, or Linux. The program is pure standard-library
  Python, so it runs from source on all three (see
  [macOS and Linux](#macos-and-linux)).

To build the standalone Windows `.exe` you additionally need **PyInstaller**
(see [Building a Windows executable](#building-a-windows-executable)).

---

## Running from source

```sh
python pota_accessible.py
```

The program starts a local server, prints its address, and opens your default
browser to the page. Close the browser window (or press `Ctrl+C` in the console)
to stop it.

### Command-line options

| Option           | Default     | Description                                                    |
| ---------------- | ----------- | -------------------------------------------------------------- |
| `--port PORT`    | `8777`      | Port to serve on.                                              |
| `--host HOST`    | `127.0.0.1` | Address to bind. Localhost only by default.                    |
| `--no-browser`   | off         | Do not auto-open a browser.                                    |
| `--no-autoexit`  | off         | Keep running after the browser window is closed (`Ctrl+C` to stop). |

Example:

```sh
python pota_accessible.py --port 9000 --no-browser
```

### macOS and Linux

There is no prebuilt binary for macOS or Linux, but the app runs identically
from source — it uses only the Python standard library and cross-platform
calls, so no code changes are needed. Most macOS and Linux systems already have
Python 3 installed as `python3`:

```sh
python3 pota_accessible.py
```

The browser auto-opens, and closing the browser window shuts the program down,
exactly as on Windows. On the rare system without Python, install it from
[python.org](https://www.python.org/downloads/) or your package manager
(e.g. `brew install python` on macOS, `sudo apt install python3` on Debian/
Ubuntu).

> **Note on native executables.** PyInstaller can produce a standalone binary
> for macOS and Linux too, but it cannot cross-compile — each platform's binary
> must be built on that platform. On macOS, an unsigned app is additionally
> blocked by Gatekeeper unless you right-click → **Open** the first time (or
> sign and notarize it with an Apple Developer ID). For these reasons, only the
> Windows `.exe` is distributed prebuilt; on macOS and Linux, run from source
> as shown above.

---

## Using the app

- **Read the spots** by navigating the table with your screen reader's table
  commands. In JAWS, move cell-to-cell with `Ctrl`+`Alt`+arrow keys; the column
  header and the row's callsign are announced with each value.
- **Filter / search** using the controls above the table. Results update as you
  type or change a selection, and the count is announced.
- **Refresh** with the *Refresh spots* button to pull the latest data.
- **Mark a contact worked** with the button at the end of each row. The spot is
  logged and removed from the list. Turn on *Show spots I've already worked
  today* to reveal them again, each with an *Unmark* button in case of a
  mistake.

---

## How "worked" tracking works

POTA credits a hunter for a contact **once per activator, park, band, and mode,
per UTC day**. This viewer follows the same rule:

- Marking a spot worked hides it **for the current UTC day**.
- If the activator moves (QSY) to a **different band or mode**, they reappear —
  because that is a new contact you can legitimately make.
- After **00:00 UTC**, the day rolls over and everyone becomes workable again.

Your worked contacts are saved to a file named **`worked_log.json`**, created
next to the program (next to the script when run from source, or next to the
`.exe` when built). It keeps full history; only the current UTC day's entries
filter the list. This file is personal data and is **not** committed to the
repository (see `.gitignore`). Delete it any time to clear your log.

---

## Building a Windows executable

The result is a single self-contained `POTA-Accessible-Spots.exe` that needs no
Python install on the target machine.

```sh
py -m pip install -r requirements-dev.txt
build.bat
```

or run PyInstaller directly:

```sh
py -m PyInstaller --onefile --windowed --name "POTA-Accessible-Spots" ^
  --distpath dist --workpath build --specpath build pota_accessible.py
```

Notes:

- `--windowed` means no console window appears when the `.exe` is double-clicked.
- `worked_log.json` is written next to the `.exe`, so the log persists between
  runs.
- The first launch of a one-file build takes a few seconds while it unpacks.
- Unsigned executables may trigger a Windows SmartScreen prompt
  ("More info" -> "Run anyway") or an antivirus false positive on first run.
  Code signing removes this but requires a certificate.

Built executables are **not** checked into the repository. Publish them as
attachments on a [GitHub Release](https://docs.github.com/en/repositories/releasing-projects-on-github).

---

## Accessibility notes

This project targets **WCAG 2.1 Level AA**. Key choices:

- Semantic `<table>` with `<caption>`, `scope="col"` headers, and `scope="row"`
  callsigns, so cell values are always announced with their meaning.
- Native, labeled form controls; no custom widgets that require ARIA guesswork.
- A polite `aria-live` status region for counts and messages that never moves
  focus.
- Focus is deliberately managed after marking a spot worked, so keyboard/screen
  reader users are not dropped to the top of the page.

Feedback from real screen-reader users is welcome — please open an issue.

---

## Data source and disclaimer

Data comes from the public POTA API endpoint
`https://api.pota.app/spot/activator`. This is an **independent,
accessibility-focused viewer** and is **not affiliated with, endorsed by, or
sponsored by Parks on the Air®**. "Parks on the Air" and "POTA" are marks of
their respective owner. Please use the API responsibly.

---

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Brian Haupt.
