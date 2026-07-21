#!/usr/bin/env python3
"""
POTA Accessible Spots Viewer
============================

A small, dependency-free local web app that presents the live Parks On The Air
"active spots" feed (https://api.pota.app/spot/activator) as a clean, semantic,
screen-reader-friendly page. Built to be usable with JAWS (and NVDA/VoiceOver).

Why this exists
---------------
The official pota.app spots page renders each spot as a list of unlabeled
values with no table headers, several unlabeled icon buttons, and a 60-second
auto-refresh that yanks a screen reader's reading position out from under the
user. This viewer instead uses:

  * a real <table> with proper column headers (JAWS announces the column name
    before each value, e.g. "Frequency, 14306"),
  * the activator callsign as a row header,
  * labeled filter/search controls,
  * a MANUAL refresh button (nothing changes unless you ask), and
  * a polite aria-live status line that announces the result count without
    stealing focus.

The Python process fetches the POTA API server-side, so the browser only ever
talks to this local server -- no cross-origin issues.

Usage
-----
    python pota_accessible.py

Then open http://127.0.0.1:8777/ in your browser (the script tries to open it
for you). Stop the server with Ctrl+C.

Options:
    python pota_accessible.py --port 9000     # use a different port
    python pota_accessible.py --no-browser    # don't auto-open a browser
"""

import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

__version__ = "1.1.1"

POTA_SPOTS_URL = "https://api.pota.app/spot/activator"
USER_AGENT = "POTA-Accessible-Viewer/%s (local personal use)" % __version__
FETCH_TIMEOUT = 15  # seconds

# Directory to store persistent data next to the program. When frozen by
# PyInstaller, __file__ points at a temporary extraction dir that is deleted on
# exit, so we must use the executable's own location instead -- otherwise the
# worked log would silently vanish every run.
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Persistent "worked" log. A contact is unique per activator + park + band +
# mode + UTC day (POTA's own dupe rule), so working an activator again after a
# QSY to another band/mode -- or on the next UTC day -- is treated as new.
WORKED_FILE = os.path.join(APP_DIR, "worked_log.json")
_worked_lock = threading.Lock()


def _is_android():
    """True when running under Android (Termux, Pydroid 3, etc.).

    Android's browser can't be launched reliably via webbrowser.open(), so we
    detect it to skip auto-open and print the URL for the user instead. Uses
    only environment variables, keeping the standard-library-only guarantee.
    """
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return True
    if "com.termux" in os.environ.get("PREFIX", "") or os.environ.get("TERMUX_VERSION"):
        return True
    return False

# --- Auto-exit heartbeat --------------------------------------------------- #
# The page pings /api/ping every couple of seconds. When the browser window is
# closed the pings stop; a watchdog thread then shuts the server down. The gap
# during a page refresh is far shorter than IDLE_TIMEOUT, and multiple open
# tabs each keep it alive, so neither triggers a false shutdown.
PING_INTERVAL_MS = 2000     # how often the page pings (client side)
IDLE_TIMEOUT = 6.0          # seconds of silence after which we exit
_activity_lock = threading.Lock()
_last_activity = [0.0]      # time.monotonic() of the last page contact
_ever_connected = [False]   # has a browser ever contacted us?


def note_activity():
    with _activity_lock:
        _last_activity[0] = time.monotonic()
        _ever_connected[0] = True


# --------------------------------------------------------------------------- #
# Data fetching
# --------------------------------------------------------------------------- #
def fetch_spots():
    """Fetch the current activator spots from the POTA API.

    Returns a Python list (parsed JSON). Raises on network/parse failure so the
    caller can turn it into a clean HTTP error for the browser.
    """
    req = Request(POTA_SPOTS_URL, headers={"User-Agent": USER_AGENT,
                                           "Accept": "application/json"})
    with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("Unexpected API response shape (expected a list).")
    return data


# --------------------------------------------------------------------------- #
# Worked log (persistent, UTC-day scoped)
# --------------------------------------------------------------------------- #
def utc_today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _norm(s):
    return str(s if s is not None else "").strip().upper()


def make_key(activator, reference, band, mode):
    """Contact identity: activator|park|band|mode (all normalized)."""
    return "|".join([_norm(activator), _norm(reference), _norm(band), _norm(mode)])


def _read_all_unlocked():
    if not os.path.exists(WORKED_FILE):
        return []
    try:
        with open(WORKED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def _write_all_unlocked(entries):
    tmp = WORKED_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, WORKED_FILE)  # atomic on the same filesystem


def today_worked_keys():
    """Return (utc_date, sorted list of keys worked on that UTC day)."""
    today = utc_today()
    with _worked_lock:
        entries = _read_all_unlocked()
    keys = sorted({e.get("key") for e in entries if e.get("date") == today
                   and e.get("key")})
    return today, keys


def add_worked(activator, reference, band, mode):
    today = utc_today()
    key = make_key(activator, reference, band, mode)
    with _worked_lock:
        entries = _read_all_unlocked()
        if not any(e.get("key") == key and e.get("date") == today
                   for e in entries):
            entries.append({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "date": today,
                "key": key,
                "activator": _norm(activator),
                "reference": _norm(reference),
                "band": _norm(band),
                "mode": _norm(mode),
            })
            _write_all_unlocked(entries)
    return today


def remove_worked(activator, reference, band, mode):
    """Undo: drop today's entries matching this contact (keeps history for
    other days)."""
    today = utc_today()
    key = make_key(activator, reference, band, mode)
    with _worked_lock:
        entries = _read_all_unlocked()
        kept = [e for e in entries
                if not (e.get("key") == key and e.get("date") == today)]
        if len(kept) != len(entries):
            _write_all_unlocked(kept)
    return today


# --------------------------------------------------------------------------- #
# The page (HTML + CSS + JS), served as one document.
# All rendering/filtering happens client-side against the JSON we proxy.
# --------------------------------------------------------------------------- #
PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>POTA Active Spots (Accessible)</title>
<style>
  :root {
    --bg: #ffffff;
    --fg: #14181f;
    --muted: #4a5361;
    --line: #c3cad4;
    --row-alt: #f2f5f9;
    --accent: #0b5fff;
    --accent-fg: #ffffff;
    --focus: #b8860b;
    --qrt: #8a1c1c;
    --worked: #146c2e;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1319;
      --fg: #eef2f7;
      --muted: #aab4c2;
      --line: #313a48;
      --row-alt: #171d26;
      --accent: #5b9dff;
      --accent-fg: #06101f;
      --focus: #ffd24a;
      --qrt: #ff8a8a;
      --worked: #6bd88f;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--fg);
    font: 16px/1.5 system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  }
  .skip-link {
    position: absolute; left: -9999px; top: 0;
    background: var(--accent); color: var(--accent-fg);
    padding: 10px 14px; z-index: 100; border-radius: 0 0 6px 0;
  }
  .skip-link:focus { left: 0; }
  header, main { max-width: 1200px; margin: 0 auto; padding: 16px; }
  h1 { font-size: 1.5rem; margin: 0 0 4px; }
  .sub { color: var(--muted); margin: 0 0 12px; }

  form { margin: 0 0 16px; }
  fieldset {
    border: 1px solid var(--line); border-radius: 8px;
    padding: 12px 14px; margin: 0;
  }
  legend { font-weight: 600; padding: 0 6px; }
  .controls {
    display: flex; flex-wrap: wrap; gap: 12px 18px; align-items: flex-end;
  }
  .field { display: flex; flex-direction: column; gap: 4px; }
  .field label { font-weight: 600; }
  .field input, .field select {
    font: inherit; padding: 7px 9px; min-width: 150px;
    border: 1px solid var(--line); border-radius: 6px;
    background: var(--bg); color: var(--fg);
  }
  .checkfield { flex-direction: row; align-items: center; gap: 8px; }
  .checkfield label { font-weight: 400; }
  /* The .field input rule above is meant for text/select inputs; keep
     checkboxes their natural size and hard against their label. */
  .checkfield input[type="checkbox"] {
    width: auto; min-width: 0; padding: 0; margin: 0; flex: none;
  }
  .btns { display: flex; gap: 10px; align-items: flex-end; }
  button {
    font: inherit; font-weight: 600; cursor: pointer;
    padding: 8px 16px; border-radius: 6px;
    border: 1px solid var(--accent); background: var(--accent); color: var(--accent-fg);
  }
  button.secondary { background: var(--bg); color: var(--fg); border-color: var(--line); }

  /* Strong, consistent focus indicator for keyboard users. */
  a:focus-visible, button:focus-visible, input:focus-visible,
  select:focus-visible, th[tabindex]:focus-visible {
    outline: 3px solid var(--focus); outline-offset: 2px;
  }

  .status {
    margin: 12px 0; padding: 8px 12px;
    border-left: 4px solid var(--accent); background: var(--row-alt);
    border-radius: 0 6px 6px 0;
  }
  .status.error { border-left-color: var(--qrt); }

  .tablewrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; }
  caption { text-align: left; font-weight: 600; margin-bottom: 8px; }
  th, td {
    text-align: left; padding: 8px 10px;
    border-bottom: 1px solid var(--line); vertical-align: top;
  }
  thead th {
    position: sticky; top: 0; background: var(--bg);
    border-bottom: 2px solid var(--fg);
  }
  tbody tr:nth-child(even) { background: var(--row-alt); }
  tbody th[scope="row"] { font-weight: 700; white-space: nowrap; }
  .freq { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .qrt td, .qrt th { color: var(--qrt); }
  tr.worked td, tr.worked th { opacity: 0.62; }
  .workedtag { font-weight: 700; color: var(--worked); white-space: nowrap; }
  .actioncell { white-space: nowrap; }
  .rowbtn { padding: 5px 12px; font-size: 0.9rem; }
  .parkref { font-weight: 600; }
  .parkname { color: var(--muted); }
  .empty { padding: 20px; text-align: center; color: var(--muted); }
  .visually-hidden {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
  }
  footer { max-width: 1200px; margin: 24px auto 40px; padding: 0 16px; color: var(--muted); }
  footer a { color: var(--accent); }

  /* Give the focusable scroll region a clear keyboard focus indicator. */
  .tablewrap:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }

  /* ---- Small screens (phones) ---------------------------------------- */
  @media (max-width: 640px) {
    header, main { padding: 12px; }
    h1 { font-size: 1.3rem; }

    /* Let the scrolling table span the full screen width instead of being
       inset by the page padding. The negative margins cancel main's padding;
       the first/last cells re-add a small inset so text isn't flush to the
       screen edge. */
    .tablewrap { margin: 0 -12px; }
    caption { padding: 0 12px; }
    th:first-child, td:first-child { padding-left: 12px; }
    th:last-child, td:last-child { padding-right: 12px; }

    /* Tighter cells and slightly smaller type fit more columns before the
       user has to scroll sideways. */
    table { font-size: 0.95rem; }
    th, td { padding: 6px 8px; }
    .rowbtn { padding: 5px 10px; }

    /* Stack the filter controls full-width rather than wrapping awkwardly. */
    .field, .checkfield, .btns { width: 100%; }
    /* Full-width text/select inputs, but leave checkboxes their natural size
       (the checkfields carry the .field class too). */
    .field input:not([type="checkbox"]), .field select { width: 100%; min-width: 0; }
    .btns button { flex: 1; }
  }
</style>
</head>
<body>
<a class="skip-link" href="#results">Skip to spots table</a>

<header>
  <h1>POTA Active Spots</h1>
  <p class="sub">An accessible view of the live Parks On The Air activator spots feed.</p>

  <form id="filters" aria-label="Filter and search spots">
    <fieldset>
      <legend>Filter spots</legend>
      <div class="controls">
        <div class="field">
          <label for="q">Search (callsign, park, reference, comment)</label>
          <input type="search" id="q" name="q" autocomplete="off"
                 placeholder="e.g. K1ABC, US-2876, sunlight">
        </div>
        <div class="field">
          <label for="band">Band</label>
          <select id="band" name="band"><option value="">All bands</option></select>
        </div>
        <div class="field">
          <label for="mode">Mode</label>
          <select id="mode" name="mode"><option value="">All modes</option></select>
        </div>
        <div class="field">
          <label for="program">Program / entity</label>
          <select id="program" name="program"><option value="">All programs</option></select>
        </div>
        <div class="field">
          <label for="sort">Sort by</label>
          <select id="sort" name="sort">
            <option value="time-desc">Most recent first</option>
            <option value="time-asc">Oldest first</option>
            <option value="freq-asc">Frequency, low to high</option>
            <option value="call-asc">Callsign, A to Z</option>
          </select>
        </div>
        <div class="field checkfield">
          <input type="checkbox" id="hideqrt" name="hideqrt" checked>
          <label for="hideqrt">Hide QRT (finished) spots</label>
        </div>
        <div class="field checkfield">
          <input type="checkbox" id="showworked" name="showworked">
          <label for="showworked">Show spots I&rsquo;ve already worked today</label>
        </div>
        <div class="btns">
          <button type="button" id="refresh">Refresh spots</button>
          <button type="button" class="secondary" id="clear">Clear filters</button>
        </div>
      </div>
    </fieldset>
  </form>

  <!-- Polite live region: announces counts/errors without moving focus. -->
  <p class="status" id="status" role="status" aria-live="polite">Loading spots&hellip;</p>
</header>

<main id="results">
  <div class="tablewrap" role="region"
       aria-label="Spots table (scroll sideways to see all columns)" tabindex="0">
    <table aria-describedby="status">
      <caption id="tcaption">Active POTA spots</caption>
      <thead>
        <tr>
          <th scope="col">Age</th>
          <th scope="col">Callsign</th>
          <th scope="col">Frequency (kHz)</th>
          <th scope="col">Band</th>
          <th scope="col">Mode</th>
          <th scope="col">Park</th>
          <th scope="col">Location</th>
          <th scope="col">Spotter</th>
          <th scope="col">Comment</th>
          <th scope="col">Action</th>
        </tr>
      </thead>
      <tbody id="tbody">
        <tr><td class="empty" colspan="10">Loading&hellip;</td></tr>
      </tbody>
    </table>
  </div>
</main>

<footer>
  <p>Data from the public POTA API. This is an independent accessibility-focused
     viewer and is not affiliated with Parks On The Air&reg;.
     Official site: <a href="https://pota.app/">pota.app</a>.</p>
  <p>Contacts you mark as worked are saved to <code>worked_log.json</code> and
     hidden for the current UTC day. Because POTA counts a contact per
     activator, park, band and mode, an activator who moves to another band or
     mode &mdash; or who is spotted again on the next UTC day &mdash; will
     reappear so you can work them again.</p>
  <p>POTA Accessible Spots v{{VERSION}}</p>
</footer>

<script>
"use strict";

// ----- Band plan (kHz ranges) -------------------------------------------- //
const BANDS = [
  ["2200m",135.7,137.8],["630m",472,479],["160m",1800,2000],["80m",3500,4000],
  ["60m",5250,5450],["40m",7000,7300],["30m",10100,10150],["20m",14000,14350],
  ["17m",18068,18168],["15m",21000,21450],["12m",24890,24990],["10m",28000,29700],
  ["6m",50000,54000],["2m",144000,148000],["1.25m",222000,225000],
  ["70cm",420000,450000],["33cm",902000,928000],["23cm",1240000,1300000],
];
function bandFor(freqKhz) {
  const f = parseFloat(freqKhz);
  if (!isFinite(f)) return "";
  for (const [name, lo, hi] of BANDS) { if (f >= lo && f <= hi) return name; }
  return "";
}

// ----- Helpers ------------------------------------------------------------ //
function parseUtc(s) {
  // API times look like "2026-07-20T16:11:12" with no zone => treat as UTC.
  if (!s) return null;
  const t = Date.parse(s.endsWith("Z") ? s : s + "Z");
  return isNaN(t) ? null : t;
}
function ageText(ms) {
  if (ms == null) return "";
  let sec = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (sec < 60) return sec + " sec ago";
  const min = Math.floor(sec / 60);
  if (min < 60) return min + (min === 1 ? " min ago" : " min ago");
  const hr = Math.floor(min / 60);
  return hr + (hr === 1 ? " hr ago" : " hr ago");
}
function isQrt(spot) {
  return String(spot.comments || "").toUpperCase().includes("QRT");
}
function programOf(ref) {
  // reference looks like "US-2876"; the program/entity is the part before "-".
  const m = String(ref || "").match(/^([A-Za-z0-9]+)-/);
  return m ? m[1].toUpperCase() : "";
}
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escAttr(s) { return esc(s).replace(/"/g, "&quot;"); }

// Must match the server's make_key(): activator|reference|band|mode, upper.
function keyFor(s) {
  return [s.call, s.ref, s.band, s.mode]
    .map(x => String(x == null ? "" : x).trim().toUpperCase()).join("|");
}

// ----- State -------------------------------------------------------------- //
let ALL = [];              // last-fetched spots (decorated)
let WORKED = new Set();    // keys worked on the current UTC day
let WORKED_DATE = "";      // the UTC date those keys belong to
const el = (id) => document.getElementById(id);

function decorate(spots) {
  return spots.map(s => {
    const ms = parseUtc(s.spotTime);
    return {
      raw: s,
      call: (s.activator || "").toUpperCase(),
      freq: s.frequency || "",
      band: bandFor(s.frequency),
      mode: (s.mode || "").toUpperCase(),
      ref: s.reference || "",
      parkName: s.name || s.parkName || "",
      loc: s.locationDesc || "",
      spotter: (s.spotter || "").toUpperCase(),
      comment: s.comments || "",
      program: programOf(s.reference),
      timeMs: ms,
      qrt: isQrt(s),
    };
  });
}

function rebuildSelect(sel, values, keepValue) {
  const current = keepValue !== undefined ? keepValue : sel.value;
  const firstOpt = sel.querySelector("option"); // the "All ..." option
  sel.innerHTML = "";
  sel.appendChild(firstOpt);
  for (const v of values) {
    const o = document.createElement("option");
    o.value = v; o.textContent = v;
    sel.appendChild(o);
  }
  // Restore selection if still available.
  sel.value = [...sel.options].some(o => o.value === current) ? current : "";
}

function refreshFilterOptions() {
  const bands = [...new Set(ALL.map(s => s.band).filter(Boolean))]
    .sort((a, b) => BANDS.findIndex(x => x[0] === a) - BANDS.findIndex(x => x[0] === b));
  const modes = [...new Set(ALL.map(s => s.mode).filter(Boolean))].sort();
  const progs = [...new Set(ALL.map(s => s.program).filter(Boolean))].sort();
  rebuildSelect(el("band"), bands);
  rebuildSelect(el("mode"), modes);
  rebuildSelect(el("program"), progs);
}

function currentFilters() {
  return {
    q: el("q").value.trim().toLowerCase(),
    band: el("band").value,
    mode: el("mode").value,
    program: el("program").value,
    sort: el("sort").value,
    hideqrt: el("hideqrt").checked,
    showworked: el("showworked").checked,
  };
}

function applyFilters() {
  const f = currentFilters();
  ALL.forEach(s => { s.worked = WORKED.has(keyFor(s)); });
  let rows = ALL.filter(s => {
    if (!f.showworked && s.worked) return false;
    if (f.hideqrt && s.qrt) return false;
    if (f.band && s.band !== f.band) return false;
    if (f.mode && s.mode !== f.mode) return false;
    if (f.program && s.program !== f.program) return false;
    if (f.q) {
      const hay = [s.call, s.ref, s.parkName, s.loc, s.spotter, s.comment]
        .join(" ").toLowerCase();
      if (!hay.includes(f.q)) return false;
    }
    return true;
  });

  rows.sort((a, b) => {
    switch (f.sort) {
      case "time-asc":  return (a.timeMs || 0) - (b.timeMs || 0);
      case "freq-asc":  return (parseFloat(a.freq) || 0) - (parseFloat(b.freq) || 0);
      case "call-asc":  return a.call.localeCompare(b.call);
      default:          return (b.timeMs || 0) - (a.timeMs || 0); // time-desc
    }
  });

  renderRows(rows);
  return rows.length;
}

function renderRows(rows) {
  const tbody = el("tbody");
  if (!rows.length) {
    tbody.innerHTML = '<tr><td class="empty" colspan="10">' +
      'No spots match the current filters.</td></tr>';
    return;
  }
  const html = rows.map(s => {
    const park = esc(s.ref) +
      (s.parkName ? ' <span class="parkname">' + esc(s.parkName) + "</span>" : "");
    const comment = s.comment
      ? esc(s.comment)
      : '<span class="visually-hidden">no comment</span>';

    const rowClass = [s.qrt ? "qrt" : "", s.worked ? "worked" : ""]
      .filter(Boolean).join(" ");
    const data =
      'data-act="' + escAttr(s.call) + '" data-ref="' + escAttr(s.ref) +
      '" data-band="' + escAttr(s.band) + '" data-mode="' + escAttr(s.mode) + '"';
    const who = s.call + " at " + s.ref +
      (s.band ? " on " + s.band : "") + (s.mode ? " " + s.mode : "");
    const action = s.worked
      ? '<span class="workedtag">✓ Worked</span> ' +
        '<button type="button" class="rowbtn secondary" data-worked="1" ' + data +
        ' aria-label="Remove ' + escAttr(who) +
        ' from today’s worked log">Unmark</button>'
      : '<button type="button" class="rowbtn" data-worked="0" ' + data +
        ' aria-label="Mark ' + escAttr(who) + ' as worked">Mark worked</button>';

    return (
      '<tr' + (rowClass ? ' class="' + rowClass + '"' : "") + '>' +
        '<td>' + esc(ageText(s.timeMs)) + "</td>" +
        '<th scope="row">' + esc(s.call) + "</th>" +
        '<td class="freq">' + esc(s.freq) + "</td>" +
        "<td>" + esc(s.band) + "</td>" +
        "<td>" + esc(s.mode) + "</td>" +
        '<td class="parkref">' + park + "</td>" +
        "<td>" + esc(s.loc) + "</td>" +
        "<td>" + esc(s.spotter) + "</td>" +
        "<td>" + comment + "</td>" +
        '<td class="actioncell">' + action + "</td>" +
      "</tr>"
    );
  }).join("");
  tbody.innerHTML = html;
}

function setStatus(msg, isError) {
  const s = el("status");
  s.textContent = msg;
  s.classList.toggle("error", !!isError);
}

async function loadSpots(announcePrefix) {
  setStatus((announcePrefix || "") + "Loading spots…");
  try {
    const resp = await fetch("/api/spots", { cache: "no-store" });
    if (!resp.ok) throw new Error("Server returned " + resp.status);
    const data = await resp.json();
    ALL = decorate(data);
    await loadWorked();
    refreshFilterOptions();
    const shown = applyFilters();
    const total = ALL.length;
    const when = new Date().toLocaleTimeString();
    const detail = shown === total
      ? total + (total === 1 ? " spot" : " spots")
      : shown + " of " + total + " spots shown";
    setStatus("Updated at " + when + ". " + detail + ".");
  } catch (err) {
    setStatus("Could not load spots: " + err.message +
      ". Check your internet connection and press Refresh spots.", true);
  }
}

async function loadWorked() {
  try {
    const resp = await fetch("/api/worked", { cache: "no-store" });
    if (!resp.ok) return;
    const w = await resp.json();
    WORKED = new Set(w.keys || []);
    WORKED_DATE = w.date || "";
  } catch (e) { /* non-fatal: spots still display, just unfiltered */ }
}

// Mark/unmark a spot as worked. Persists on the server, then re-renders and
// moves focus somewhere sensible so a screen-reader user is never dropped.
async function toggleWorked(btn) {
  const payload = {
    activator: btn.dataset.act, reference: btn.dataset.ref,
    band: btn.dataset.band, mode: btn.dataset.mode,
  };
  const wasWorked = btn.dataset.worked === "1";
  const btns = [...document.querySelectorAll("tbody .rowbtn")];
  const idx = Math.max(0, btns.indexOf(btn));
  btn.disabled = true;
  try {
    const resp = await fetch(wasWorked ? "/api/unworked" : "/api/worked", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error("server " + resp.status);
    const data = await resp.json();
    WORKED = new Set(data.keys || []);
    WORKED_DATE = data.date || WORKED_DATE;
    const shown = applyFilters();
    focusAfterAction(idx);
    const label = payload.activator + " at " + payload.reference;
    setStatus((wasWorked ? "Removed from worked log: " : "Logged as worked: ") +
      label + ". " + shown + " of " + ALL.length + " spots shown.");
  } catch (err) {
    btn.disabled = false;
    setStatus("Could not update the worked log: " + err.message +
      ". Please try again.", true);
  }
}

function focusAfterAction(prevIdx) {
  const btns = [...document.querySelectorAll("tbody .rowbtn")];
  if (!btns.length) { el("refresh").focus(); return; }
  (btns[Math.min(prevIdx, btns.length - 1)] || btns[0]).focus();
}

// ----- Wire up ------------------------------------------------------------ //
function onFilterChange() {
  const n = applyFilters();
  const total = ALL.length;
  setStatus(n === total
    ? (total + (total === 1 ? " spot." : " spots."))
    : (n + " of " + total + " spots shown."));
}

document.addEventListener("DOMContentLoaded", () => {
  el("refresh").addEventListener("click", () => loadSpots());
  el("clear").addEventListener("click", () => {
    el("q").value = "";
    el("band").value = ""; el("mode").value = "";
    el("program").value = ""; el("hideqrt").checked = true;
    el("showworked").checked = false;
    el("sort").value = "time-desc";
    onFilterChange();
    el("q").focus();
  });
  ["q", "band", "mode", "program", "sort", "hideqrt", "showworked"].forEach(id =>
    el(id).addEventListener("input", onFilterChange));
  // Click on a row's Mark worked / Unmark button (event delegation).
  el("tbody").addEventListener("click", (e) => {
    const btn = e.target.closest("button.rowbtn");
    if (btn) toggleWorked(btn);
  });
  // Prevent Enter in the search box from reloading via implicit submit.
  el("filters").addEventListener("submit", e => e.preventDefault());

  // Heartbeat: lets the local server shut itself down when this window is
  // closed. Interval is kept well under the server's idle timeout so a normal
  // page refresh never looks like a close. keepalive lets an in-flight ping
  // finish even as the page unloads.
  const ping = () =>
    fetch("/api/ping", { cache: "no-store", keepalive: true }).catch(() => {});
  ping();
  setInterval(ping, 2000);

  loadSpots();
});
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "POTAAccessible/" + __version__

    def _send(self, code, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/ping":
            note_activity()
            self._send(204, b"", "text/plain; charset=utf-8")
            return
        note_activity()
        if path == "/" or path == "/index.html":
            page = PAGE_HTML.replace("{{VERSION}}", __version__)
            self._send(200, page, "text/html; charset=utf-8")
        elif path == "/api/spots":
            try:
                data = fetch_spots()
                self._send(200, json.dumps(data),
                           "application/json; charset=utf-8")
            except (HTTPError, URLError) as e:
                self._send(502, json.dumps({"error": "upstream", "detail": str(e)}),
                           "application/json; charset=utf-8")
            except Exception as e:  # noqa: BLE001 - surface anything as JSON
                self._send(500, json.dumps({"error": "internal", "detail": str(e)}),
                           "application/json; charset=utf-8")
        elif path == "/api/worked":
            today, keys = today_worked_keys()
            self._send(200, json.dumps({"date": today, "keys": keys}),
                       "application/json; charset=utf-8")
        else:
            self._send(404, "Not found", "text/plain; charset=utf-8")

    def do_POST(self):
        note_activity()
        path = self.path.split("?", 1)[0]
        if path not in ("/api/worked", "/api/unworked"):
            self._send(404, "Not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, OSError):
            self._send(400, json.dumps({"error": "bad request body"}),
                       "application/json; charset=utf-8")
            return

        activator = payload.get("activator")
        reference = payload.get("reference")
        band = payload.get("band")
        mode = payload.get("mode")
        if not activator or not reference:
            self._send(400, json.dumps({"error": "activator and reference required"}),
                       "application/json; charset=utf-8")
            return

        if path == "/api/worked":
            add_worked(activator, reference, band, mode)
        else:
            remove_worked(activator, reference, band, mode)

        today, keys = today_worked_keys()
        self._send(200, json.dumps({"date": today, "keys": keys}),
                   "application/json; charset=utf-8")

    def log_message(self, fmt, *args):
        # Keep the console quiet: skip the frequent heartbeat pings entirely.
        msg = fmt % args
        if "/api/ping" in msg:
            return
        sys.stderr.write("  %s - %s\n" % (self.address_string(), msg))


def start_idle_watchdog(httpd, idle_timeout):
    """Shut the server down once the browser stops sending heartbeats.

    Only arms after the first contact from a page, so running headless (e.g.
    --no-browser with nothing connected) never triggers a shutdown.
    """
    def run():
        while True:
            time.sleep(1.0)
            with _activity_lock:
                connected = _ever_connected[0]
                idle = time.monotonic() - _last_activity[0]
            if connected and idle > idle_timeout:
                print("\nBrowser window closed. Shutting down.")
                httpd.shutdown()  # safe: called from a non-serving thread
                return
    threading.Thread(target=run, daemon=True).start()


def _fatal(msg):
    """Report a fatal startup error. In a windowed build there is no console,
    so also surface it as a Windows dialog (which screen readers announce)."""
    print(msg)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, msg, "POTA Accessible Spots", 0x10)  # MB_ICONERROR
    except Exception:  # noqa: BLE001 - non-Windows or no user32; console print
        pass           #            already happened above.


def main():
    # A windowed (no-console) PyInstaller build has no stdout/stderr, so any
    # print() or log write would raise. Redirect them to a sink to be safe.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    ap = argparse.ArgumentParser(description="Accessible POTA spots viewer.")
    ap.add_argument("--port", type=int, default=8777, help="Port (default 8777).")
    ap.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    ap.add_argument("--no-browser", action="store_true",
                    help="Do not auto-open a browser.")
    ap.add_argument("--no-autoexit", action="store_true",
                    help="Keep running even after the browser window is closed.")
    ap.add_argument("--version", action="version",
                    version="POTA Accessible Spots " + __version__)
    args = ap.parse_args()

    url = "http://%s:%d/" % (args.host, args.port)
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        _fatal("Could not start POTA Accessible Spots on %s.\n\n%s\n\n"
               "The program may already be running, or another app is using "
               "port %d. Close the other window, or start it on a different "
               "port with:  POTA-Accessible-Spots.exe --port 9000"
               % (url, e, args.port))
        sys.exit(1)

    android = _is_android()

    print("POTA Accessible Spots Viewer")
    print("  Serving at: " + url)
    # The idle watchdog auto-stops the server when the browser window closes.
    # It relies on a ~2s heartbeat from the page, but mobile browsers freeze
    # background-tab timers, so on Android a refresh or app-switch would look
    # like a close and kill the server. Android runs from Pydroid/Termux where
    # the user stops the session manually anyway, so skip auto-exit there.
    if args.no_autoexit or android:
        print("  Press Ctrl+C to stop.")
    else:
        print("  Close the browser window (or press Ctrl+C) to stop.")
        start_idle_watchdog(httpd, IDLE_TIMEOUT)
    if android and not args.no_browser:
        # webbrowser.open() can't reliably launch Android's browser, so guide
        # the user to open the URL themselves instead of silently failing.
        print("")
        print("  Android detected \u2014 auto-open skipped.")
        print("  Open this address in your browser (Chrome, etc.):")
        print("")
        print("      " + url)
        print("")
        print("  Tip: long-press to copy the line above, or type it into the")
        print("  address bar. Leave this session running while you use it.")
    elif not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        httpd.shutdown()
    print("Server stopped.")


if __name__ == "__main__":
    main()
