# GUI Sequencer — production quality

PyQt5 GUI for building and running ARTIQ experimental sequences (package
`sequencer_gui` in `src/`, run with `python -m sequencer_gui`; HEROS/ARTIQ
integration via `sequencer_hero.py`, see `requirements-artiq.txt`). I don't
review GUI code line by line; I judge it by behaviour. It must be robust in
daily lab use.

## Standard
- Production quality: robust error handling, no crashes from bad input or an
  unavailable ARTIQ/HEROS connection, clear user-facing error messages,
  nothing that freezes the UI.
- Blocking work (compilation, network, file I/O on large sequences) off the
  GUI thread; UI updates only from the GUI thread (signals/slots).
- Follow the existing architecture described in `docs/functional-architecture.md`:
  domain logic in `domain/`, widgets in `ui/`, I/O in `sequence_io.py` /
  `persistence.py`. Keep domain logic free of Qt.
- Never break loading of existing saved sequences; changes to the file
  format need a backward-compatible loader.
- Add tests (pytest, in a `tests/` folder) for non-UI logic you touch,
  especially sequence building, scan plans and serialization.
- Keep `docs/functional-architecture.md` up to date when the structure changes.

## How to work here
- You may refactor and restructure on your own judgment, but explain the
  change in a short summary of behaviour, not a line-by-line tour.
- Ask before changing anything that alters the timing or content of what is
  sent to ARTIQ (pulse timings, channel mapping, compiled sequences).
- Ignore `venv_sequencer/` and `*.egg-info/`.
