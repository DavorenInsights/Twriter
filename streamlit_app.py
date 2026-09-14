"""
FIELD NOTES TYPEWRITER — STREAMLIT EDITION
==========================================
Uses the exact V6.7 Pillow rendering engine from renderer.py.
"""

import io
import os
import random
import tempfile
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image

import renderer


st.set_page_config(
    page_title="Field Notes Typewriter",
    page_icon="📝",
    layout="wide",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
      div[data-testid="stMetricValue"] {font-size: 1.05rem;}
      .small-note {opacity:0.72; font-size:0.88rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Field Notes Typewriter")
st.caption("Streamlit edition — same V6.7 rendering engine as the local Spyder version.")

# ----------------------------
# Persistent state
# ----------------------------
if "generated_pages" not in st.session_state:
    st.session_state.generated_pages = []
if "generation_seed" not in st.session_state:
    st.session_state.generation_seed = None
if "last_settings" not in st.session_state:
    st.session_state.last_settings = None


def uploaded_to_temp(uploaded, suffix):
    """Materialise one Streamlit upload to a temporary file path."""
    if uploaded is None:
        return None
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(path, "wb") as f:
        f.write(uploaded.getvalue())
    return path


def image_to_png_bytes(image):
    bio = io.BytesIO()
    image.save(bio, format="PNG", dpi=(renderer.DPI, renderer.DPI))
    return bio.getvalue()


def all_pages_zip(pages, template_name):
    bio = io.BytesIO()
    safe = template_name.lower().replace(" ", "_")
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        for i, image in enumerate(pages, 1):
            z.writestr(f"{safe}_{i:02d}.png", image_to_png_bytes(image))
    return bio.getvalue()


# ----------------------------
# Controls
# ----------------------------
with st.sidebar:
    st.header("Page")
    template_name = st.selectbox(
        "Template",
        ["A5 Field Note", "Square Note"],
        index=0,
    )
    paper_name = st.selectbox(
        "Paper",
        list(renderer.PAPER_COLOURS.keys()),
        index=list(renderer.PAPER_COLOURS.keys()).index("Ivory"),
    )
    paper_style = st.selectbox(
        "Paper style",
        ["Plain", "Faint Ruled", "Graph", "Dotted"],
        index=0,
    )
    ribbon_age = st.selectbox(
        "Ribbon age",
        ["Fresh", "Used", "Fading"],
        index=1,
    )
    imperfections = st.slider(
        "Imperfections",
        min_value=0,
        max_value=100,
        value=40,
        step=1,
    )

    st.divider()
    st.header("Optional image")
    photo_upload = st.file_uploader(
        "Choose image",
        type=["png", "jpg", "jpeg", "webp", "tif", "tiff"],
        key="photo_upload",
    )
    photo_style = st.selectbox(
        "Image style",
        ["Polaroid (aged)", "Thermal", "Dot-Matrix"],
        index=0,
        disabled=photo_upload is None,
    )
    photo_mode = st.selectbox(
        "Image mode",
        ["Colour", "B&W"],
        index=0,
        disabled=photo_upload is None,
    )
    photo_position = st.selectbox(
        "Image position",
        ["Auto", "Top Left", "Top Right", "Bottom Left", "Bottom Right"],
        index=0,
        disabled=photo_upload is None,
    )

    st.divider()
    st.header("Optional stamp")
    stamp_upload = st.file_uploader(
        "Choose scanned stamp",
        type=["png", "jpg", "jpeg", "webp", "tif", "tiff"],
        key="stamp_upload",
    )
    stamp_position = st.selectbox(
        "Stamp position",
        ["Auto", "Bottom Left", "Bottom Right"],
        index=0,
        disabled=stamp_upload is None,
    )

left, right = st.columns([0.95, 1.05], gap="large")

with left:
    st.subheader("Text")
    default_text = """WHAT IS DEBT

This is money you borrow and
are expected to pay back.

The lender does not normally own
part of your project. Instead, you agree
how and when the money will be repaid...
usually with interest.

TAKEAWAY
--------
Can you repay the money?
"""
    raw = st.text_area(
        "Field note text",
        value=default_text,
        height=520,
        label_visibility="collapsed",
    )

    col_a, col_b = st.columns([1, 1])
    with col_a:
        generate = st.button("Generate", type="primary", use_container_width=True)
    with col_b:
        regenerate = st.button("New variation", use_container_width=True)

    st.markdown(
        '<div class="small-note">“New variation” keeps your settings but creates a fresh physical variation.</div>',
        unsafe_allow_html=True,
    )

# ----------------------------
# Generate only on command
# ----------------------------
if generate or regenerate:
    geom = renderer.template_geometry(template_name)

    max_chars = max(
        1,
        (geom["PAGE_W"] - geom["LEFT"] - geom["RIGHT"]) // geom["CHAR_PITCH"]
    )
    max_lines = max(
        1,
        (geom["PAGE_H"] - geom["TOP"] - geom["BOTTOM"]) // geom["LINE_PITCH"]
    )

    lines = renderer.wrap_fixed(raw, max_chars)
    chunks = [lines[i:i+max_lines] for i in range(0, len(lines), max_lines)] or [[""]]

    master_seed = random.SystemRandom().randint(0, 2_000_000_000)
    pages = []

    photo_path = None
    stamp_path = None
    try:
        if photo_upload is not None:
            suffix = Path(photo_upload.name).suffix or ".png"
            photo_path = uploaded_to_temp(photo_upload, suffix)

        if stamp_upload is not None:
            suffix = Path(stamp_upload.name).suffix or ".png"
            stamp_path = uploaded_to_temp(stamp_upload, suffix)

        for pageno, chunk in enumerate(chunks):
            page_seed = master_seed + pageno * 104729

            rendered = renderer.render_page(
                chunk,
                ribbon_age,
                int(imperfections),
                page_seed,
                template_name=template_name,
                paper_name=paper_name,
                paper_style=paper_style,
            )

            if photo_path:
                style = photo_style
                if style.startswith("Polaroid"):
                    style = "Polaroid"

                rendered = renderer.add_mixed_media_photo(
                    rendered,
                    photo_path,
                    photo_mode,
                    style,
                    photo_position,
                    template_name,
                    chunk,
                    page_seed,
                )

            if stamp_path:
                rendered = renderer.add_stamp_overlay(
                    rendered,
                    stamp_path,
                    stamp_position,
                    template_name,
                    page_seed,
                )

            pages.append(rendered)

        st.session_state.generated_pages = pages
        st.session_state.generation_seed = master_seed
        st.session_state.last_settings = {
            "template": template_name,
            "paper": paper_name,
            "paper_style": paper_style,
            "ribbon": ribbon_age,
            "imperfections": int(imperfections),
            "photo": photo_upload is not None,
            "stamp": stamp_upload is not None,
        }

    finally:
        for path in (photo_path, stamp_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


# ----------------------------
# Preview and downloads
# ----------------------------
with right:
    st.subheader("Preview")

    pages = st.session_state.generated_pages
    if not pages:
        st.info("Generate a page to preview it here.")
    else:
        page_index = st.number_input(
            "Page",
            min_value=1,
            max_value=len(pages),
            value=1,
            step=1,
        ) - 1

        st.image(
            pages[page_index],
            use_container_width=True,
        )

        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "Download current PNG",
                data=image_to_png_bytes(pages[page_index]),
                file_name=f"{template_name.lower().replace(' ', '_')}_{page_index+1:02d}.png",
                mime="image/png",
                use_container_width=True,
            )
        with dl2:
            st.download_button(
                "Download all pages ZIP",
                data=all_pages_zip(pages, template_name),
                file_name="field_notes_pages.zip",
                mime="application/zip",
                use_container_width=True,
            )

        settings = st.session_state.last_settings or {}
        st.caption(
            f"{len(pages)} page(s) • "
            f"{settings.get('template', template_name)} • "
            f"{settings.get('paper_style', paper_style)} • "
            f"ribbon {settings.get('ribbon', ribbon_age).lower()} • "
            f"imperfections {settings.get('imperfections', imperfections)}/100"
        )
