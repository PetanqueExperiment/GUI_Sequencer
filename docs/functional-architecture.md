# Functional architecture — GUI Sequencer

This document describes how **Petanque Sequencer** works: purpose, layers, data model, integration with HERO/ARTIQ/PyCam, and main control flows. It is intended for onboarding, design reviews, and future development.

**Last aligned with codebase:** May 2026.

---

## 1. Purpose

**GUI Sequencer** is a **PyQt5** desktop application for editing **ArtiQ experimental sequences**:

- A **timeline matrix**: per device row, per time step — digital ON/OFF (where applicable), delays (µs), and analog parameters (or *hold*).
- **Blocks**: named, reorderable segments; only **enabled** blocks are concatenated for runtime.
- **Complete** tab: merged view of all enabled blocks (same shape sent to the host).
- **Parameter scans**: vary matrix values over a grid; integrate with **PyCam** for data tagging.
- **Live run/pause** and **ARTIQ master** supervision via **HERO** (Petanque stack).

Persistence: versioned **JSON** sequence files plus local UI settings (`~/.sequencer_gui/settings.json`).

---

## 2. Context diagram (external systems)

```mermaid
flowchart TB
    subgraph User["User"]
        U[Operator / physicist]
    end

    subgraph GUI["GUI Sequencer (PyQt5)"]
        MW[MainWindow + panels]
        ST[SequenceAppState]
        DOM[Domain: Document / Model]
    end

    subgraph Disk["Local disk"]
        JSON["Sequence .json files"]
        CFG["~/.sequencer_gui/settings.json"]
    end

    subgraph HERO["HERO (Petanque)"]
        SEQ["Sequencer_HERO\n(in-process)"]
        ATOM_S["atomiq-scheduler"]
        ATOM_E["atomiq-experimentdb"]
        PYCAM["PyCam HERO"]
    end

    subgraph Host["Experimental host"]
        ARTIQ["ARTIQ master\n(atomiq_master)"]
        RUN["Sequence execution / scans"]
    end

    U --> MW
    MW <--> ST
    ST <--> DOM
    ST --> JSON
    ST --> CFG
    ST --> SEQ
    MW --> ATOM_S
    MW --> ATOM_E
    MW --> PYCAM
    SEQ --> RUN
    ATOM_S --> ARTIQ
    ATOM_E --> ARTIQ
    PYCAM --> RUN
```

---

## 3. Layered architecture

```mermaid
flowchart TB
    subgraph L1["1. Application entry"]
        MAIN["main.py"]
        SI["single_instance"]
        LOAD["sequence_io + persistence\n(initial load)"]
    end

    subgraph L2["2. Presentation (UI)"]
        TB["SequenceToolbar\nSave / Load / Run"]
        AP["ArtiqPanel\nstatus + experiments"]
        SP["ScanPanel\nplan + PyCam"]
        BS["BlockStripWidget"]
        TAB["QTabBar\nComplete / Block N"]
        CM["ChannelMatrix"]
        STP["StaticParametersPanel"]
    end

    subgraph L3["3. Application logic"]
        SAS["SequenceAppState\nmutations + Qt signals"]
        SCAN["scan_plan"]
    end

    subgraph L4["4. Domain"]
        DOC["SequenceDocument"]
        BLK["SequenceBlock"]
        MOD["SequenceModel"]
        MERGE["merge_blocks()\nenabled blocks → runtime timeline"]
    end

    subgraph L5["5. Software object catalog"]
        DYN["dynamical registry\nAOM, RF, Shutter, TTL, DDS, Current"]
        STA["static registry\n(between-shot params; extensible)"]
    end

    subgraph L6["6. Backend / integration"]
        BE["SequenceBackendProtocol"]
        HDB["HeroDictBackend"]
        NOP["NoOpBackend"]
        HERO["Sequencer_HERO"]
    end

    MAIN --> SI
    MAIN --> LOAD
    MAIN --> SAS
    MAIN --> MW["MainWindow"]

    MW --> TB & AP & SP & BS & TAB & CM & STP
    TB & SP & BS & TAB & CM & STP --> SAS
    SAS --> DOC
    DOC --> BLK
    SAS --> MOD
    MOD --> MERGE
    SAS --> SCAN
    DYN & STA --> DOC
    SAS --> BE
    BE --> HDB & NOP
    HDB --> HERO
```

### Layer responsibilities

| Layer | Responsibility |
|-------|----------------|
| **Entry** | Single GUI instance, icon/font, load last sequence or defaults, attach `HeroDictBackend` or `NoOpBackend`. |
| **UI** | Reflect `SequenceAppState`; edit matrix, blocks, scan config, ArtiQ actions; no business rules duplicated long-term. |
| **App state** | Own `SequenceDocument`, active tab, scan/run flags; emit signals; call backend on every commit. |
| **Domain** | Immutable dataclasses; `merge_blocks` for runtime; column mapping Complete ↔ block index. |
| **Software objects** | Per-row device type: which params exist, ON/OFF strip, defaults, display. |
| **Backend** | Push snapshot JSON to `Sequencer_HERO`; sync run/pause and burst shot budget. |

---

## 4. Data model

### 4.1 Concepts

| Concept | Meaning |
|---------|---------|
| **Row** | One hardware/software channel (default **20** rows, `DEFAULT_DEVICE_ROWS`). Has label + **dynamical** object id (e.g. AOM, DDS). |
| **Block** | Named timeline segment: `cols` time steps, `enabled` flag, channels, delays, analog, optional accent color. |
| **Column** | One time step: delay (µs), booleans, analog cells (`float` or hold). |
| **Complete** | Tab index `-1`: UI shows `merge_blocks(document, enabled_only=True)`. Edits map back to underlying blocks. |
| **Scan** | Axes: device label, param id, timestep label, value list; temporarily patches matrix then restores. |

### 4.2 Entity relationship

```mermaid
erDiagram
    SequenceDocument ||--|{ SequenceBlock : contains
    SequenceDocument {
        int rows
        string row_labels
        string row_software
    }
    SequenceBlock {
        string name
        bool enabled
        int cols
        dict channels
        dict delays_us
        dict analog
    }
    SequenceModel ||--|| SequenceDocument : "per-block or merge_blocks view"
```

### 4.3 Key types (source)

| Type | Module | Role |
|------|--------|------|
| `SequenceDocument` | `domain/document.py` | Shared rows + ordered `blocks`. |
| `SequenceBlock` | `domain/document.py` | Timeline payload for one block. |
| `SequenceModel` | `domain/model.py` | Flat view: rows × cols for one block or merged timeline. |
| `AnalogStored` | `domain/analog_stored.py` | Float or hold sentinel. |
| `SequenceAppState` | `app/state.py` | Mutable session; `COMPLETE_TAB_INDEX = -1`. |

**Runtime snapshot:** `merge_blocks(doc, enabled_only=True)` → `SequenceModel` passed to `backend.apply()`. Full document + name → `backend.sync_sequence_snapshot()` (same shape as saved JSON via `live_sequence_file_dict`).

---

## 5. Main functional flows

### 5.1 Editing the sequence

```mermaid
sequenceDiagram
    participant U as User
    participant UI as ChannelMatrix / DeviceRow
    participant S as SequenceAppState
    participant D as SequenceDocument
    participant B as Backend

    U->>UI: Edit cell / delay / device type
    UI->>S: set_channel / set_analog / set_delay_us / set_row_software / …
    S->>D: Immutable with_block / with_row_software
    S-->>UI: Qt signals (model_changed, channels_changed, …)
    S->>B: sync_sequence_snapshot + apply(merge_blocks enabled)
```

### 5.2 Save and load

```mermaid
flowchart LR
    TB[SequenceToolbar] -->|save_sequence| IO[sequence_io JSON v8]
    IO --> FILE[.json on disk]
    FILE -->|load_sequence| TB
    TB -->|replace_document| ST[SequenceAppState]
    PERS[persistence] -->|last path, row labels, window geometry| CFG[settings.json]
```

- Format id: `sequencer_gui_sequence`, version **8** (`sequence_io.FORMAT_VERSION`).
- Blocks store `device_rows["0"]…` with `states` and analog param lists (`frequency`, `amplitude`, …).
- Older files with fewer rows are **upgraded** on load to `DEFAULT_DEVICE_ROWS`.

### 5.3 Live run / pause

```mermaid
flowchart LR
    RUN_BTN[Run/Pause toolbar] --> ST[set_run_sequence]
    ST --> HERO[Sequencer_HERO.set_run_sequence]
    ST --> PYCAM[prepare_live_experiment]
    POLL[poll_host_run_sequence ~300ms] --> HERO
    HERO --> ST
```

- `BURST_SHOTS_UNLIMITED` (-1): live mode until user pauses.
- Scan mode uses `sync_burst_shots(n)` then `set_run_sequence(True)` per step.
- A scan that completes all its shots restores the matrix, then returns to live mode (`prepare_live_experiment` + `resume_live_sequence`). An interrupted or failed scan stays paused.

### 5.4 Parameter scan

```mermaid
sequenceDiagram
    participant SP as ScanPanel
    participant S as SequenceAppState
    participant P as scan_plan
    participant PYC as PyCam HERO

    SP->>S: scan_parameters, repetitions, label
    SP->>P: build_scan_points
    SP->>S: prepare_scan_matrix_restore
    loop Each scan point
        SP->>S: apply_scan_point
        SP->>PYC: set_parameter_scan_order + start experiment
        SP->>PYC: poll shots_seen
    end
    SP->>S: restore_scan_matrix
```

Scan label availability (red/blue/green) comes from `pycam_repository.classify_scan_label` (today’s data folders).

On scan start, `pycam_repository.save_scan_sequence_snapshot` writes the sequence JSON (same v8 format as the Save button) into the PyCam data folder of the scan: `{PYCAM_DATA_DIRECTORY}/{Y}/{m}/{d}/{scan label}/sequence.json`. Written after PyCam accepted the experiment name and before the first scan point is applied, so the snapshot holds the configured matrix. A reused label keeps the earlier file and writes `sequence_{HHMMSS}.json`. Failure only warns; the scan continues.

**Scan saved with the sequence.** The Save button and the scan snapshot store the Scan panel in the sequence file, as an optional top-level `scan` key next to `document` (still v8): `{"label", "repetitions", "axes": [{"device", "param", "timestep", "values"}]}`, every axis field being the text shown in the panel. An empty panel (no label, no axis) writes no key. The key exists only on disk: `live_sequence_file_dict` (host sync, AI revision hash) never contains it.

On Load and at startup (last sequence), `sequence_io.load_sequence_file` returns the scan and `SequenceAppState.set_scan_plan` fills the panel. A file without `scan` (all older files) leaves the panel as it is. A malformed `scan` never blocks loading: the sequence loads, the panel is left alone and a warning is shown. While a scan is running, the file's scan is not applied. Labels that no longer exist in the document are loaded as text and rejected at Start scan, as for a hand-typed scan. The visualizer ignores the key.

### 5.5 ArtiQ master panel

```mermaid
flowchart LR
    AP[ArtiqPanel] -->|connect| H_S[atomiq-scheduler HERO]
    AP -->|connect| H_E[atomiq-experimentdb HERO]
    AP -->|submit / interrupt| ACT[atomiq_actions]
    ACT --> H_S
    AP -->|poll| STAT[atomiq_status]
```

Default sequencer experiment key: `Sequencer_mode.py` (`ATOMIQ_SEQUENCER_MODE_EXPERIMENT_KEY`).

A failed HERO connection is not retried automatically. **Reconnect** drops both stubs and runs discovery again in the background; running experiments are not affected.

### 5.6 Application startup

```mermaid
flowchart TD
    START[main] --> SINGLE{Single instance?}
    SINGLE -->|no| EXIT[MessageBox + exit]
    SINGLE -->|yes| LOAD[Default doc or last JSON]
    LOAD --> HERO_OK{Sequencer_HERO importable?}
    HERO_OK -->|yes| WITH[HeroDictBackend + Sequencer_HERO context]
    HERO_OK -->|no| NOOP[NoOpBackend stderr warning]
    WITH --> WIN[MainWindow.show]
    NOOP --> WIN
```

Bypass single instance: `SEQUENCER_ALLOW_MULTIPLE=1`. Optional HERO preload: `SEQUENCER_HERO_INIT_JSON`.

---

## 6. Main window layout (UI map)

`MainWindow` (`ui/main_window.py`) vertical layout:

1. **Top row:** `SequenceToolbar` | `ArtiqPanel` | `ScanPanel` (stretch)
2. **Block strip:** `BlockStripWidget` — enable, reorder, add/remove blocks
3. **Tabs:** Complete + one tab per block
4. **Matrix row:** `ChannelMatrix` (stretch) | `StaticParametersPanel` (collapsible) — column header ☰ drags a column (live preview, committed on drop, Esc cancels; within one block on Complete); right-click the header to duplicate (copy inserted to the right) or delete the column (a block keeps at least one). The timestep label row is currently hidden (`_SHOW_TIMESTEP_LABEL_ROW`)

On close: commit row/column labels, save row labels and window geometry to settings.

---

## 7. Software objects (device catalog)

### 7.1 Dynamical (timeline) — `software_objects/dynamical/`

Registered in `dynamical/registry.py` (`CATALOG_ORDER`):

| Object id | Typical role |
|-----------|----------------|
| AOM | ON/OFF + amplitude |
| RF source | RF analog parameters |
| Shutter | ON/OFF |
| TTL | ON/OFF |
| DDS | Frequency (detuning), etc. |
| Current source | Current analog parameter |

Each implements `SoftwareObject` (`protocol.py`): `has_on_off`, `analog_parameters` (`AnalogParameterSpec`).

`get_object(id)` returns a stub for unknown ids (safe load of old files).

### 7.2 Static (between shots) — `software_objects/static/`

Same registry pattern as dynamical (`registry.py`, `register`, `get_object`, `iter_objects`, `CATALOG_ORDER`). VOA devices are defined in `static/voa.py` (ten instances, amplitude **0–5 V**). UI: `StaticParametersPanel`. Storage: `SequenceDocument.static_values`, JSON `document.static`. Matrix row dropdown uses dynamical catalog only.

### 7.3 Re-exports

`software_objects/__init__.py` re-exports dynamical `get_object`, `iter_objects` for backward compatibility.

---

## 8. HERO and process identity

Constants in `process_identity.py`:

| Symbol | Value | Usage |
|--------|-------|--------|
| `HERO_INSTANCE_NAME` | `Sequencer_HERO` | In-process `LocalHERO`; JSON snapshot + run/burst |
| `CONTROL_HERO_INSTANCE_NAME` | `Sequencer_Control_HERO` | Remote control API for scripts / AI agents (§8.1) |
| `PYCAM_HERO_INSTANCE_NAME` | `PyCam_HERO` | Scan + live experiment |
| `ATOMIQ_SCHEDULER_HERO_NAME` | `atomiq-scheduler` | Scheduler status / submit |
| `ATOMIQ_EXPERIMENTDB_HERO_NAME` | `atomiq-experimentdb` | List experiments |
| `PYCAM_LIVE_EXPERIMENT_NAME` | `Running_without_scan` | Live run repo name |
| `BURST_SHOTS_UNLIMITED` | `-1` | Unlimited shots in live mode |

`Sequencer_HERO` (`sequencer_hero.py`):

- Holds `_sequence_data` dict (same as `dict` attribute for heros capabilities).
- `set_sequence_data`, `set_run_sequence`, `set_burst_shots`.
- Parameter revision / ack for cross-process stale detection (`get_seq_parameters_stale`, etc.).

`HeroDictBackend` (`app/hero_dict_backend.py`): on each document change, `set_sequence_data(live_sequence_file_dict(...))`; `apply(merged model)` is a no-op (snapshot carries full document).

### 8.1 Remote control API (`remote_control/`)

`SequencerControl_HERO` (`remote_control/control_hero.py`) is a second in-process `LocalHERO`, separate from the ARTIQ data path, for scripts and AI agents. Started in `main.py` after the main window; if it fails, the GUI runs without it (stderr warning).

- **Reads:** `get_overview()`, `get_devices()`, `get_block(block)`, `get_complete_timeline()`.
- **Proposals:** `submit_proposal(json)`, `get_proposal_status(id)` (see §8.2). Nothing in the API changes the sequence directly.
- Every method returns a JSON string `{"ok": true, "result": …}` or `{"ok": false, "error": "…"}`.
- HEROS serves calls on zenoh threads. `GuiThreadInvoker` (`remote_control/gui_invoker.py`) takes a consistent snapshot of `SequenceAppState` on the GUI thread (5 s timeout; a call that has not started by then is cancelled). The description is built off the GUI thread by the Qt-free `remote_control/describe.py`.
- Addressing as in the scan panel: label first, a digit string is a 0-based index. Analog cells: number, `"hold"` or `"ramp"`; the Complete view adds `resolved` values. Each reply carries a `revision` hash of the live sequence JSON.
- Manual check: `scripts/remote_control_probe.py`.

**MCP adapter for AI agents** (`remote_control/mcp_server.py`, extra `agent` = `mcp>=2.3`). A separate process that the agent's client (Claude Code) starts over stdio; it opens a `RemoteHERO` per tool call (no state, survives GUI restarts) and never runs inside the GUI. Read-only tools: `sequencer_overview`, `sequencer_devices`, `sequencer_timeline(block, rows, include_unused)`. Replies are compact text from the Qt-free `remote_control/agent_views.py`: ON strips as column ranges, analog values only where stored (hold in between), unused rows by name only (about 5× smaller than the JSON). Registered for all sessions of the lab user: `claude mcp add --scope user sequencer -- <venv python> -m sequencer_gui.remote_control.mcp_server`.

MCP tools for proposals: `sequencer_propose(summary, base_revision, changes, scan)` and `sequencer_proposal_status(id)`.

### 8.2 AI proposals and the approval window

```mermaid
sequenceDiagram
    participant AI as AI agent (MCP)
    participant H as SequencerControl_HERO
    participant C as ProposalController (GUI thread)
    participant W as ProposalWindow
    participant S as SequenceAppState
    AI->>H: submit_proposal(changes, scan, base_revision)
    H->>C: submit (via GuiThreadInvoker)
    C->>C: parse + check (proposals.py), revision must match
    C->>W: open window (nothing applied)
    W->>C: Accept n of N (ticked changes)
    C->>S: replace_document (one step, Undo kept)
    W->>C: Accept scan
    C->>S: set_scan_plan (Scan panel filled, not started)
    AI->>H: get_proposal_status(id)
```

- `remote_control/proposals.py` (no widgets): JSON shape, checks against the live document (rows, columns on the Complete timeline as label / `cN` / `N`, parameter ranges, ramp only on AOM/piezo, ON only on devices with ON/OFF, delay 0.004 µs to 1e9 µs, one change per cell), applying a subset, scan check with the Start-scan rules (`resolve_scan_bindings`).
- `remote_control/proposal_controller.py`: one proposal at a time (a second one is refused while parts are undecided). Changes and scan are decided separately. Accept changes is refused while a scan runs or if the sequence changed since the proposal (revision check); applied with `replace_document`, one Undo while the sequence is unchanged since. Accept scan re-checks the scan and calls `SequenceAppState.set_scan_plan`; the operator starts it. Closing the window counts as "dismissed". Events are logged to `~/.sequencer_gui/ai_proposals.jsonl`.
- `ui/proposal_window.py`: read-only preview matrix (own `SequenceAppState`), changes with tick boxes (old value red → new green), scan line with per-axis values and the current value, Show current, Accept / Reject / Undo per part. Cells are outlined via `ChannelMatrix.timelineCellWidget` (orange change, purple scanned cell). User-facing text says "AI".

---

## 9. Module reference

| Module / package | Function |
|------------------|----------|
| `main.py` | `QApplication`, backend selection, `MainWindow` |
| `single_instance.py` | Windows/file lock — one GUI instance |
| `app/state.py` | Central state, scan restore, tab/block ops |
| `app/backend.py` | `SequenceBackendProtocol`, `NoOpBackend` |
| `app/hero_dict_backend.py` | HERO dict sync |
| `domain/document.py` | Document, block, merge, Complete column mapping |
| `domain/model.py` | Flat model, analog resolution (hold chain) |
| `domain/scan.py` | `ScanParameter`, `ScanPlan` (Scan panel content, no Qt) |
| `sequence_io.py` | JSON v8 load/save (sequence + optional saved scan), validation, hero block import |
| `persistence.py` | `~/.sequencer_gui/settings.json` |
| `scan_plan.py` | Scan bindings, points, duration estimate |
| `sequencer_hero.py` | `Sequencer_HERO` LocalHERO implementation |
| `remote_control/` | `SequencerControl_HERO` remote API, GUI-thread invoker, Qt-free descriptions and agent text views, MCP server, AI proposals and their controller |
| `ui/proposal_window.py` | Approval window for AI proposals |
| `atomiq_status.py` | Scheduler snapshot |
| `atomiq_actions.py` | Submit / interrupt experiments |
| `pycam_experiment.py` | Live + scan PyCam calls |
| `pycam_repository.py` | Scan label folder classification, sequence snapshot next to PyCam data |
| `ui/channel_matrix.py` | Grid widget |
| `ui/device_row.py` | Per-row editors |
| `ui/block_strip.py` | Block management UI |
| `ui/live_reorder.py` | Drag-to-reorder row of cards (☰ handle), shared by the block strip and the scan parameter cards |
| `ui/sequence_toolbar.py` | File + run + timing labels |
| `ui/scan_panel.py` | Scan UI + PyCam loop |
| `ui/artiq_panel.py` | ArtiQ status and actions |
| `ui/static_parameters_panel.py` | Static params sidebar |

---

## 10. Dependencies and deployment

| Dependency | Role |
|------------|------|
| PyQt5 | UI |
| numpy | HERO / ARTIQ types in `Sequencer_HERO` |
| Petanque `heros` (editable) | `LocalHERO`, ARTIQ compile — see `requirements-artiq.txt` |
| atomiq / ARTIQ master | Optional; ArtiqPanel |
| PyCam HERO | Optional; scan and live run |

**Run:** `python -m sequencer_gui` or console script `sequencer-gui`.

**Without heros:** GUI runs with `NoOpBackend` (no live dict sync); stderr warns on import failure.

---

## 11. Design notes for future work

- **Static parameters:** UI panel present; register types in `software_objects/static/` and wire state/backend when host API is ready.
- **Complete tab:** Edits resolve to block-local columns via `merged_enabled_timeline_col_to_block`; read-only if no block enabled (placeholder timeline).
- **Run sequence flag:** Not persisted in JSON; host-only via HERO.
- **Scan metadata:** Label, repetitions, parameter list live in `SequenceAppState` (not in `SequenceDocument`) and are saved in the sequence file under `scan` (§5.4); execution ties to PyCam + matrix patching.

---

## 12. Related files to keep in sync

When changing behavior, update this doc if you alter:

- `FORMAT_VERSION` or JSON schema (`sequence_io.py`)
- HERO instance names (`process_identity.py`)
- Default row count (`DEFAULT_DEVICE_ROWS` in `domain/model.py`)
- Dynamical catalog (`dynamical/registry.py` `CATALOG_ORDER`)
- Main window composition (`ui/main_window.py`)
