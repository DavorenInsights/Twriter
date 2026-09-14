# Field Notes Typewriter — Streamlit Edition

This version is deliberately separate from the working local Spyder V6.7 app.

The **renderer is the same V6.7 Pillow engine**:
- real calibrated scanned typewriter glyphs
- frozen A5 and square-note geometry
- ribbon age and imperfections
- Plain / Faint Ruled / Graph / Dotted paper
- Polaroid (aged) / Thermal / Dot-Matrix image treatments
- optional real scanned stamp
- 300 DPI PNG output

## Run locally

Open a terminal in this folder:

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Streamlit Community Cloud

Upload this whole folder to a GitHub repository. The important files are:

- `streamlit_app.py`
- `renderer.py`
- `requirements.txt`
- `typewriter_glyphs_v6/`

Set the app entry point to:

`streamlit_app.py`

## Important

Do not move or rename `typewriter_glyphs_v6`. It must remain beside
`renderer.py`.

## Why this version should behave better than the early Streamlit experiments

The typewriter output no longer depends on a cloud machine finding the right
Courier/typewriter font. It uses the bundled scans of the real typewriter
strikes, so the visual rendering is controlled by Pillow just like the local
desktop version.

The Streamlit interface only handles controls, uploads, preview and downloads.
It does not alter the typewriter rendering itself.
