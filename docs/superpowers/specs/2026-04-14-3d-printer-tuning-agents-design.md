# 3D Printer Tuning Agents — Design Spec

**Date:** 2026-04-14  
**Project:** `/home/jonathan/projects/3d-printer-tuning-agents`  
**Printer:** Flashforge Adventurer 5M Pro · 0.4mm nozzle · `192.168.1.137`  
**Slicer:** OrcaSlicer v2.3.x (Linux)  
**Status:** Approved for implementation

---

## 1. Goal

Build a team of AI agents that iteratively fine-tune OrcaSlicer print settings for the Flashforge AD5M Pro, optimizing for **quality end products printed in the shortest possible time**. Agents use the printer's camera (via Home Assistant), user pass/fail feedback, and pre-print geometry analysis to converge on optimal profiles per filament × nozzle combination.

---

## 2. Architecture

### 2.1 Overview

**Orchestrator + 4 Specialist Sub-Agents**, all backed by Claude API (`claude-sonnet-4-6`). Agents communicate exclusively with **Home Assistant** — never directly with the printer. OrcaSlicer profiles are read/written directly from the filesystem.

```
CLI / Web Dashboard
        │
        ▼
  [Orchestrator Agent]
        │
        ├── CalibrationAgent
        ├── ProfileAdvisorAgent
        ├── VisionAgent
        └── SpeedOptimizerAgent
        │
        ▼
  Home Assistant (https://192.168.1.191:8123)
        │
        ▼
  Flashforge AD5M Pro @ 192.168.1.137
```

### 2.2 Home Assistant Access

| Priority | URL | Notes |
|---|---|---|
| 1 (primary) | `https://192.168.1.191:8123` | Local LAN — lowest latency, self-signed cert (verify=False) |
| 2 (fallback) | `https://hayjo.ddns.net:8123` | DDNS — for off-network use |
| 3 (last resort) | `https://u2z6bl5jen3zvj3iibwsv8z69982e49b.ui.nabu.casa` | Nabu Casa cloud relay |

HA long-lived access token stored in `.env` (never committed). The agent tries each URL in order on startup and uses the first that responds.

### 2.3 Agent Roles

#### Orchestrator
- Entry point for all CLI commands
- Determines current phase (Calibrate / Advise / Speed)
- Delegates work to specialist agents
- Manages all confirmation gates — nothing goes to the printer or overwrites a profile without user approval (unless in Tier 3 autonomy, see §4)
- Writes approved changes to OrcaSlicer JSON profiles (always with `.bak` backup)

#### FilamentResearchAgent
- Triggered whenever a new filament × nozzle combination is added via `tune add-filament`
- Searches for manufacturer spec sheets (recommended temp range, bed temp, cooling %, max speed)
- Searches community sources for real-world tuning data specific to this filament on CoreXY/AD5M Pro printers:
  - Reddit (r/FlashForge, r/3Dprinting, r/FixMyPrint)
  - Printables and MakerWorld community profiles
  - OrcaSlicer/BambuStudio filament profile repositories
  - Filament brand forums and user reviews
- Synthesizes findings into a `research_summary.json` entry in `calibration_db.json`
- Sets initial parameter ranges and confidence scores based on community consensus (see §4.1)
- Presents findings to user for review before any test prints begin

#### CalibrationAgent
- Designs and sequences calibration test prints (temperature tower → flow rate cube → pressure advance test)
- Uses FilamentResearchAgent output as starting ranges — test prints refine within those ranges, not from scratch
- Parses VisionAgent quality scores + user feedback to converge on baseline parameter values
- Stores converged values in `calibration_db.json` keyed by `filament × nozzle`
- Tracks per-parameter confidence scores (see §4)

#### ProfileAdvisorAgent
- Reads a `.3mf` file and extracts geometry characteristics: overhang angles, wall count, support requirements, infill density, model height
- Compares geometry to calibrated baseline for the active filament × nozzle
- Produces a diff of recommended OrcaSlicer profile overrides for the specific model
- Does not run calibration prints — advisory only

#### VisionAgent
- Captures a snapshot from HA camera entity `camera.flashforge_adventurer_5m_pro_camera`
- Sends image to Claude vision API with a structured quality rubric
- Returns scores (0.0–1.0) for: stringing, layer adhesion, warping, surface finish, overall quality
- Feeds scores back to CalibrationAgent or SpeedOptimizerAgent

#### SpeedOptimizerAgent
- Starting from the calibrated baseline, proposes speed increases in ~10% increments
- After each test print + VisionAgent score, decides: keep increase or revert
- Tracks a Pareto frontier of (print_speed → quality_score) for the active filament × nozzle
- Stops when quality score drops below user-defined threshold (default: 0.80)

---

## 3. Three-Phase Workflow

### Phase 0 — Add Filament (new filaments only)
**Purpose:** Bootstrap a new filament × nozzle entry from manufacturer specs and community knowledge before any test prints.  
**Trigger:** `tune add-filament --filament "Brand Filament Name" --nozzle 0.4`

**Sequence:**
1. FilamentResearchAgent searches manufacturer site for official temp/speed specs
2. Agent searches Reddit, Printables, MakerWorld, and OrcaSlicer community repos for user-reported settings on CoreXY / AD5M Pro
3. Synthesizes community consensus into initial parameter ranges + source count
4. Presents research summary to user for review
5. User confirms → `calibration_db.json` entry created with `research_baseline`
6. Agent also checks HA history for any prior prints with this filament and merges confirmed values
7. Calibration phase begins with test prints focused only on parameters not yet community-validated

### Phase 1 — Calibrate
**Purpose:** Establish a reliable baseline for a filament × nozzle combination.  
**Trigger:** `tune calibrate --filament "ELEGOO PLA+ High Speed" --nozzle 0.4`  
**Frequency:** Run once per new filament × nozzle pair; re-run if print quality degrades unexpectedly.

**Sequence:**
1. Agent checks `calibration_db.json` for existing data and determines confidence tier (see §4)
2. If no entry exists, runs Phase 0 (add-filament) first
3. Skips test prints for parameters already at Tier 2+ confidence (bootstrapped from research or HA history)
4. Proposes next test print for unconfirmed parameters only (temp tower → flow cube → pressure advance)
5. Depending on tier: confirms with user OR proceeds autonomously
6. Sends print job to printer via HA service call (`start_print`)
7. Monitors print via HA (`binary_sensor.flashforge_printing`, `sensor.flashforge_print_progress`)
8. On completion: VisionAgent captures + scores; user optionally adds pass/fail note
9. Agent updates `calibration_db.json` with new data point, recalculates confidence scores
10. Repeats until all parameters are at Tier 2+ confidence

### Phase 2 — Advise
**Purpose:** Tailor profile settings to a specific model before slicing.  
**Trigger:** `tune advise path/to/model.3mf`

**Sequence:**
1. ProfileAdvisorAgent extracts geometry from `.3mf` (overhangs >45°, wall count, support needed, infill %, model height)
2. Loads calibrated baseline for active filament × nozzle from `calibration_db.json`
3. Produces a diff of recommended profile changes (e.g., reduce layer height, increase support angle, adjust speeds for tall/thin geometry)
4. Presents diff to user for approval
5. On approval: writes changes to OrcaSlicer profile with `.bak` backup
6. User re-slices in OrcaSlicer and prints

### Phase 3 — Speed Push
**Purpose:** Find the fastest print speed that maintains quality above threshold.  
**Trigger:** `tune speed --quality 0.8` (threshold configurable, default 0.80)  
**Prerequisite:** Calibrated baseline must exist (Tier 2+) for active filament × nozzle.

**Sequence:**
1. SpeedOptimizerAgent loads current baseline speed
2. Proposes +10% speed test print (a standard speed test geometry)
3. Confirms with user (or auto-proceeds at Tier 3)
4. Sends print, monitors completion, VisionAgent scores result
5. If score ≥ threshold: record result, propose another +10%
6. If score < threshold: revert to last passing speed, record Pareto point, done
7. Final optimal speed saved to `calibration_db.json` baseline

---

## 4. Progressive Autonomy (Phase 1)

Confirmation gates in Phase 1 shrink as calibration data accumulates. Tier is evaluated per filament × nozzle, not globally.

### 4.1 Bootstrap — Before the First Test Print

Every new filament × nozzle entry goes through a two-step bootstrap before any test prints run:

#### Step 1 — Web Research (FilamentResearchAgent)
Triggered by `tune add-filament --filament "Brand Name Filament" --nozzle 0.4`:

1. Agent searches manufacturer site for official spec sheet (temp range, bed temp, cooling, speed limits)
2. Agent searches community sources for AD5M Pro / CoreXY tuning data for this exact filament:
   - Reddit threads with user-reported settings
   - Printables / MakerWorld filament profiles and comments
   - OrcaSlicer community profile repositories
   - User reviews mentioning specific temp/speed/flow settings
3. Agent synthesizes a `research_baseline` — the community-consensus starting point with ranges
4. Presents a summary to the user for review and confirmation before proceeding

The research baseline populates `calibration_db.json` with initial ranges and sets per-parameter confidence to `community` tier (higher than zero, lower than test-validated):

```json
"research_baseline": {
  "source": "manufacturer + community",
  "retrieved": "2026-04-14",
  "nozzle_temp": { "recommended": 225, "range": [215, 235], "source_count": 12 },
  "bed_temp":    { "recommended": 60,  "range": [55, 65],   "source_count": 12 },
  "flow_rate":   { "recommended": 1.0, "range": [0.95, 1.05], "source_count": 6 },
  "max_speed":   { "recommended": 200, "range": [150, 300], "source_count": 8 },
  "cooling_fan": { "recommended": 100, "range": [80, 100],  "source_count": 9 }
}
```

#### Step 2 — HA History Bootstrap (existing filaments only)
For filaments that have already been printed (printer has run them before HA integration existed):

1. Query HA history for completed print sessions
2. Extract stable mid-print temperatures, speed distributions, fan states
3. Cross-reference with OrcaSlicer user profile files in `~/.config/OrcaSlicer/user/default/`
4. Pre-populate baseline with statistically confirmed values, skipping those parameters to Tier 2

**Bootstrap result for ELEGOO PLA+ High Speed (existing filament, confirmed from HA Apr 13 session):**

| Parameter | Bootstrapped Value | Source | Starting Tier |
|---|---|---|---|
| nozzle_temp | 225°C (median of 6,499 readings) | HA history | Tier 2 |
| bed_temp | 60°C (median of 6,744 readings) | HA history | Tier 2 |
| cooling_fan | 100% | HA history | Tier 2 |
| flow_rate | 0.98 (from OrcaSlicer profile) | Profile file | Tier 1 |
| pressure_advance | 0.042 (from OrcaSlicer profile) | Profile file | Tier 1 |
| max_speed | 225mm/s median observed | HA history | Tier 1 (needs validation) |

This means calibration for ELEGOO PLA+ can skip temperature and bed tests entirely and go straight to flow rate and pressure advance refinement.

### Tier 1 — Cold Start (0–3 print runs)
- No history. Full confirmation required for every action.
- Agent explains reasoning for every proposal.
- Every profile write and print job requires explicit user approval.

### Tier 2 — Warming Up (4–10 print runs)
- Agent auto-proceeds when:
  - Proposed value is within the proven range for that parameter
  - Change is ≤5% from the last known-good value
- Agent still confirms when:
  - Venturing outside the explored parameter range
  - Overwriting an OrcaSlicer profile
  - Starting a new test type for the first time

### Tier 3 — Confident (11+ runs, stable baseline)
- Agent runs the full calibration sequence autonomously.
- Only surfaces to user:
  - A summary after the session completes
  - Anomalies outside the expected parameter range
  - Detection of a new filament spool (brand/lot change)

### Per-Parameter Confidence Score
Each parameter tracks independently:
- `sample_count` — number of runs that tested this parameter
- `variance` — spread of values at passing quality scores (tighter = higher confidence)
- `pass_rate` — fraction of runs at the converged value that passed VisionAgent scoring

Tier thresholds (4 / 11) are configurable in `config.yaml`.

**Safety net (always active regardless of tier):**
- OrcaSlicer profiles backed up to `.bak` before every write
- `tune rollback` restores the previous profile at any time
- All Tier 3 auto-runs are logged; summary shown after each session

---

## 5. Data Model

### 5.1 Calibration Database
`calibration_db.json` — keyed by `"filament_name | nozzle_size"`:

```json
{
  "ELEGOO PLA+ High Speed | 0.4mm": {
    "confidence_tier": 2,
    "baseline": {
      "nozzle_temp": 225,
      "bed_temp": 60,
      "flow_rate": 0.98,
      "pressure_advance": 0.042,
      "max_speed": 150
    },
    "parameters": {
      "nozzle_temp": {
        "confidence": 0.87,
        "sample_count": 14,
        "proven_range": [220, 227],
        "pass_rate": 0.93
      }
    },
    "speed_pareto": [
      {"speed": 130, "quality_score": 0.94, "timestamp": "2026-04-14T10:00:00"},
      {"speed": 150, "quality_score": 0.91, "timestamp": "2026-04-14T11:30:00"}
    ],
    "run_history": []
  }
}
```

### 5.2 Print Log
One directory per print run, timestamped:

```
print_log/
└── 2026-04-14T14-30-00/
    ├── settings.json        — OrcaSlicer params used for this print
    ├── ha_snapshot.json     — Full HA state dump at print start + completion
    ├── camera_snapshot.jpg  — VisionAgent capture (end of print)
    ├── vision_score.json    — Structured quality scores per dimension
    └── feedback.txt         — User pass/fail note (optional)
```

`ha_snapshot.json` captures all available HA entities at print time — temperatures, fan speeds, TVOC, duration, XYZ position, environmental sensors — providing full context without the agents needing to track it explicitly.

### 5.3 OrcaSlicer Profiles
Read/written directly at `~/.config/OrcaSlicer/user/default/`:

```
filament/
  ELEGOO PLA+ High Speed.json
  ELEGOO PLA+ High Speed.json.bak   ← always kept before any write
process/
  0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle.json
  0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle.json.bak
```

---

## 6. Web Dashboard

**Stack:** FastAPI (Python) · Jinja2 or static HTML · `gcode-preview` JS library  
**URL:** `http://localhost:8000`

### Panels

#### Model Preview (dominant panel)
- Extracts PNG thumbnail from `.3mf` file on print start (`.3mf` is a ZIP; thumbnail at `Metadata/thumbnail.png`)
- Full interactive 3D gcode renderer using `gcode-preview` JS library
  - Scrub any layer via slider
  - Rotate/zoom the model
  - Feature-type coloring: walls (orange), infill (yellow), supports (green), upcoming layers (dark), current layer (bright highlight)
- Layer progress sourced from `sensor.flashforge_current_layer` / `sensor.flashforge_total_layers` (to be added to HA plugin — see §9)
- Polls HA every 5 seconds during active print

#### Camera Feed
- Embeds MJPEG stream from HA camera proxy
- **Snapshot** button: captures frame, saves to `print_log/`
- **Analyze** button: runs VisionAgent on current frame, displays scores

#### Current Baseline
- Table of active filament × nozzle parameters
- Per-parameter confidence score (color-coded: green ≥80%, amber 50–79%, red <50%)
- Confidence tier badge
- Rollback link

#### Pending Approvals
- Queued agent proposals with approve/reject buttons
- Shows proposed parameter diff and which agent is requesting

#### Speed vs Quality Chart
- Pareto curve for active filament × nozzle
- Color-coded: green (above threshold), amber (testing), grey (unexplored)

#### Print Log
- Recent runs: timestamp, phase, model, speed, vision score, feedback

---

## 7. Home Assistant Integration Layer

### Entities Used by Agents

| Entity | Used By | Purpose |
|---|---|---|
| `sensor.flashforge_status` | Orchestrator | Detect idle/printing/completed/paused |
| `binary_sensor.flashforge_printing` | Orchestrator | Gate: is a print active? |
| `sensor.flashforge_print_progress` | Dashboard | Progress display |
| `sensor.flashforge_estimated_time_remaining` | Dashboard | ETA display |
| `sensor.flashforge_right_nozzle_temperature` | CalibrationAgent | Verify temp reached |
| `sensor.flashforge_platform_temperature` | CalibrationAgent | Verify bed temp reached |
| `sensor.flashforge_current_print_speed` | SpeedOptimizer | Confirm speed in use |
| `sensor.flashforge_tvoc` | Print log (ha_snapshot) | Environmental context |
| `sensor.flashforge_z_axis_compensation` | Print log (ha_snapshot) | Z offset context |
| `sensor.flashforge_x/y/z_position` | Print log (ha_snapshot) | Positional context |
| `camera.flashforge_adventurer_5m_pro_camera` | VisionAgent | Snapshot capture |
| `sensor.flashforge_current_layer` | Dashboard / 3D viewer | Layer tracking (to be added) |
| `sensor.flashforge_total_layers` | Dashboard / 3D viewer | Layer tracking (to be added) |
| `sensor.flashforge_current_print_file` | Dashboard / gcode loader | Load correct gcode (to be added) |

### HA Service Calls Used

| Service | Called By | Purpose |
|---|---|---|
| `flashforge.start_print` | Orchestrator (after confirmation) | Send calibration/test print job |
| `flashforge.pause_print` | Orchestrator | Pause if anomaly detected |
| `flashforge.cancel_print` | Orchestrator | Abort on critical failure |

### Known Issues (tracked in separate HA plugin spec)
- All temperature sensors report in °F — should be °C
- `sensor.flashforge_current_print_speed` reports in in/s — should be mm/s
- `sensor.flashforge_print_speed_adjustment` shows 10000% — scaling bug (should be 100%)
- `sensor.flashforge_estimated_right_weight` always 0g — calculation missing
- `printLayer`, `targetPrintLayer`, `printFileName` exist in API but not exposed as sensors

The tuning agents will apply unit conversion at the boundary (°F→°C, in/s→mm/s) until the HA plugin fixes are shipped.

---

## 8. Tech Stack

| Component | Choice | Reason |
|---|---|---|
| Agent reasoning | Claude API (`claude-sonnet-4-6`) | Best reasoning for parameter analysis and vision |
| Language | Python 3.11+ | Existing scripts in project, rich ecosystem |
| Web server | FastAPI | Async, simple, good for streaming HA polls |
| Frontend | Vanilla JS + `gcode-preview` | No build toolchain needed for dashboard |
| HA client | `homeassistant-api` or raw `httpx` | Simple REST + WebSocket |
| Web research | Claude API `web_search` tool | Manufacturer specs + community filament data |
| Data storage | JSON files (`calibration_db.json`, `print_log/`) | No DB dependency, human-readable, git-friendly |
| Config | `config.yaml` + `.env` | YAML for tunable constants, `.env` for secrets |
| CLI | `click` or `argparse` | Simple, no extra deps |

---

## 9. Out of Scope (Separate Spec: HA Plugin Changes)

The following changes are required in `JMcCumberIO/flashforge_adventurer5m` and will be designed in a separate spec:

1. **Add missing sensors:** `printLayer` → `sensor.flashforge_current_layer`, `targetPrintLayer` → `sensor.flashforge_total_layers`, `printFileName` → `sensor.flashforge_current_print_file`
2. **Fix temperature units:** Convert all temperature sensors from °F to °C (or add a unit config option)
3. **Fix speed units:** `sensor.flashforge_current_print_speed` from in/s → mm/s
4. **Fix speed adjustment scaling:** `sensor.flashforge_print_speed_adjustment` 10000% → 100%
5. **Fix filament weight estimate:** `sensor.flashforge_estimated_right_weight` always 0g
6. **Add Lovelace 3D card:** `flashforge-3d-card.js` — custom web component using `gcode-preview`, subscribes to HA entities via WebSocket, fetches gcode from printer file API, renders live layer tracking. Ships as part of HACS integration.

---

## 10. Project Structure

```
3d-printer-tuning-agents/
├── .env                         — HA token + URLs (not committed)
├── config.yaml                  — Tier thresholds, quality threshold, speed step %
├── tune.py                      — CLI entry point
├── agents/
│   ├── orchestrator.py
│   ├── calibration_agent.py
│   ├── filament_research_agent.py  — Web research + HA history bootstrap
│   ├── profile_advisor.py
│   ├── vision_agent.py
│   └── speed_optimizer.py
├── tools/
│   ├── ha_client.py             — HA REST + WebSocket wrapper
│   ├── orca_profiles.py         — Read/write OrcaSlicer JSON profiles
│   ├── gcode_extractor.py       — Extract gcode + thumbnail from .3mf
│   ├── calibration_db.py        — calibration_db.json read/write
│   ├── web_research.py          — Web search wrapper for filament data
│   └── ha_history_bootstrap.py  — Mine HA history to seed calibration_db
├── dashboard/
│   ├── server.py                — FastAPI web server
│   ├── static/
│   │   └── gcode-preview.js     — Bundled gcode renderer
│   └── templates/
│       └── index.html           — Dashboard HTML
├── print_log/                   — Timestamped print run records
├── calibration_db.json          — Per filament×nozzle calibration data
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-04-14-3d-printer-tuning-agents-design.md
```

---

## 11. Environment File (`.env` template)

```env
# Home Assistant
HA_URL_PRIMARY=https://192.168.1.191:8123
HA_URL_FALLBACK=https://hayjo.ddns.net:8123
HA_URL_CLOUD=https://u2z6bl5jen3zvj3iibwsv8z69982e49b.ui.nabu.casa
HA_TOKEN=<long-lived access token>
HA_VERIFY_SSL=false   # primary has self-signed cert

# OrcaSlicer
ORCA_PROFILE_DIR=~/.config/OrcaSlicer/user/default

# Calibration
ACTIVE_FILAMENT=ELEGOO PLA+ High Speed
ACTIVE_NOZZLE=0.4mm
SPEED_QUALITY_THRESHOLD=0.80
SPEED_STEP_PERCENT=10
TIER2_MIN_RUNS=4
TIER3_MIN_RUNS=11
```
