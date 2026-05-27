<div align="center">
  <img src="icons/davy_64_red.png" alt="Davy Jones Logo" width="64"/>
  <h1>DavyJones</h1>
  <p>An <a href="https://github.com/EDCD/EDMarketConnector">Elite Dangerous Market Connector</a> plugin for the Davy Jones Locker piracy squadron.</p>
</div>

---

## What is this?

DavyJones connects EDMC to the Davy Jones Locker squadron API, giving piracy-focused commanders live intel and a reporting workflow without leaving the game or alt-tabbing to a browser. When you scan a ship in supercruise, the plugin checks your squadron's client list and shows their status (known client, on cooldown, or a fresh target) directly in the EDMC panel.

## Features

**Live client lookup**
Automatically checks a scanned CMDR against the squadron client list the moment your scan completes. Status appears in the EDMC panel within seconds: whether they're a known client, currently on cooldown, or not in the list yet.

**Plunder reporting**
Opens a cargo window pre-populated from your current hold. Mark what you plundered, select PvE or PvP, and submit it all from inside EDMC.

**Add client**
Submit a CMDR directly to the squadron client list. Recently scanned commanders from your current session appear as one-click suggestions so you don't have to type names manually.

**Clogger reporting**
Report commanders who combat-logged during an encounter. Attach proof (YouTube, Twitch, Imgur, Discord, Reddit, Streamable), set visibility to guild-only or shared across all guilds, and review or update your past reports from the same window.

**Stats dashboard**
Your personal ledger: total tonnage, profit, most-looted commodity, PvP/PvE breakdown, full entry history, and monthly summaries. Mirrors the dashboard on davyjones.org.

**In-game HUD overlay (optional)**
If [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) is installed, scan results and confirmations are pushed directly to your HUD as colour-coded banners. No alt-tabbing required. The plugin works normally without it.

## Requirements

- [Elite Dangerous Market Connector](https://github.com/EDCD/EDMarketConnector) v5+
- A Davy Jones Locker API key (available via the squadron Discord)
- [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) *(optional, for in-game HUD)*

## Installation

1. Download or clone this repository.
2. Place the `DavyJones` folder inside your EDMC plugins directory.
   - Find it via EDMC: **File → Settings → Plugins → Open plugins folder**
3. Restart EDMC.
4. Open **Settings → DavyJones** and paste your API key.

## Configuration

All settings live under **File → Settings → DavyJones** in EDMC.

| Setting | Description |
|---|---|
| API base URL | The squadron API endpoint. Leave as default unless you've been told otherwise. |
| API key | Your personal key from the Davy Jones Discord. Identifies you server-side. |
| Overlay toggles | Enable or disable HUD messages per event type (scan results, plunder confirmations, etc.). |

Use the **overlay test buttons** in settings to verify placement before going into the game.

## Privacy

This plugin sends data to `davyjones.org`:

- CMDR names you scan in-game (for client list lookups)
- Your cargo selection and CMDR name when you submit a plunder report
- CMDR name, reason, and optional proof URL when you submit a clogger report
- Nothing is sent until you've entered an API key, and all submissions are manual

No data is sent automatically. If you do not want any scan data leaving your machine, do not install this plugin.

## File layout

```
DavyJones/
├── load.py               # EDMC entry point, journal hooks, API layer
├── overlay.py            # EDMCModernOverlay integration
├── cargo_window.py       # Plunder report window
├── stats_window.py       # Stats dashboard window
├── add_client_window.py  # Add client window
├── clogging_window.py    # Clogger report window
├── dj_theme.py           # Shared palette and widget factories
└── icons/                # Plugin icons (red, white, orange variants)
```

## Documentation

- [Screen guide](docs/screens.md) — walkthrough of every window with screenshots

---

> **Disclaimer:** This project is an independent community tool and is not affiliated with, endorsed by, or connected to Elite Dangerous, Frontier Developments, or any of their subsidiaries. Elite Dangerous is a trademark of Frontier Developments plc.
