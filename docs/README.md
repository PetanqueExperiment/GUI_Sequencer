# GUI Sequencer — documentation

Documentation for the **Petanque Sequencer** (ArtiQ experimental sequencer GUI).

| Document | Description |
|----------|-------------|
| [functional-architecture.md](functional-architecture.md) | Functional diagrams, data model, flows, HERO integration, module map |
| [artiq-voa-integration.md](artiq-voa-integration.md) | Apply GUI VOA static values to ARTIQ hardware (`set_amplitude`) |

## Quick start

```bash
pip install -e .
# For live HERO / ARTIQ sync (optional):
# pip install -r requirements-artiq.txt  # see file for Petanque heros fork

python -m sequencer_gui
# or: sequencer-gui
```

On Windows, `Start_Sequencer_GUI.bat` launches the app.

## Source layout (high level)

```
src/sequencer_gui/
  main.py              # Entry point, single instance, HERO backend wiring
  app/                 # SequenceAppState, backends
  domain/              # SequenceDocument, SequenceModel, merge logic
  software_objects/    # Device type catalog (dynamical + static)
  ui/                  # PyQt5 widgets (matrix, scan, ArtiQ, toolbar, …)
  sequence_io.py       # JSON save/load (format version 8)
  sequencer_hero.py    # In-process Sequencer_HERO (LocalHERO)
  atomiq_*.py          # ARTIQ master via atomiq HEROs
  pycam_*.py           # PyCam scan / live experiment integration
```

See [functional-architecture.md](functional-architecture.md) for full detail.
