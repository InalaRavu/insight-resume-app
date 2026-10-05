"""Tests for DOCX text extraction.

Modern CV templates are built as tables with merged cells and floating text
boxes. Two defects here corrupted the prompt before the model ever saw it:
a merged cell was read once per grid position it spans (one CV extracted four
times over, and the model reported twelve employers for six), and drawing
layout coordinates were read as text.
"""
import io
import os

import pytest
from docx import Document

os.environ.setdefault("ALLOW_ANONYMOUS_AUTH", "true")

from fastapi import HTTPException  # noqa: E402

from src.app import extract_raw_text  # noqa: E402


def _as_bytes(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_merged_cells_are_extracted_once():
    """A cell spanning several columns must not repeat per grid position."""
    doc = Document()
    table = doc.add_table(rows=2, cols=4)
    merged = table.cell(0, 0).merge(table.cell(0, 3))
    merged.text = "Apr15-Mar24 with Atos Global IT SS Pvt. Ltd."
    table.cell(1, 0).text = "Other content"

    text = extract_raw_text(_as_bytes(doc), "cv.docx")
    assert text.count("Atos Global IT SS") == 1


def test_vertically_merged_cells_are_extracted_once():
    doc = Document()
    table = doc.add_table(rows=4, cols=2)
    merged = table.cell(0, 0).merge(table.cell(3, 0))
    merged.text = "Feb07-Apr15 with Wipro Ltd."

    text = extract_raw_text(_as_bytes(doc), "cv.docx")
    assert text.count("Wipro Ltd.") == 1


def test_nested_table_content_is_captured():
    doc = Document()
    outer = doc.add_table(rows=1, cols=1)
    inner = outer.cell(0, 0).add_table(rows=1, cols=1)
    inner.cell(0, 0).text = "Nested achievement bullet"

    text = extract_raw_text(_as_bytes(doc), "cv.docx")
    assert text.count("Nested achievement bullet") == 1


def test_body_and_table_text_both_survive():
    doc = Document()
    doc.add_paragraph("PROFESSIONAL SUMMARY")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "Architect at Insight Direct"

    text = extract_raw_text(_as_bytes(doc), "cv.docx")
    assert "PROFESSIONAL SUMMARY" in text
    assert "Architect at Insight Direct" in text


def test_drawing_coordinates_are_not_read_as_text():
    """<wp:posOffset> and <wp:extent> end in 't' but are not text runs."""
    doc = Document()
    p = doc.add_paragraph("Since Apr24 with Insight Direct")
    drawing_xml = (
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        '<w:drawing><wp:anchor><wp:positionH><wp:posOffset>848995109855</wp:posOffset>'
        '</wp:positionH><wp:extent cx="123" cy="456"/></wp:anchor></w:drawing></w:r>'
    )
    from docx.oxml import parse_xml
    p._p.append(parse_xml(drawing_xml))

    text = extract_raw_text(_as_bytes(doc), "cv.docx")
    assert "Since Apr24 with Insight Direct" in text
    assert "848995109855" not in text


def test_tabs_become_spaces_not_run_together_words():
    doc = Document()
    p = doc.add_paragraph()
    run = p.add_run("Process Owner")
    run.add_tab()
    p.add_run("Apr15-Oct18")

    text = extract_raw_text(_as_bytes(doc), "cv.docx")
    assert "Process Owner Apr15-Oct18" in text


def test_legacy_doc_is_rejected_with_guidance():
    with pytest.raises(HTTPException) as excinfo:
        extract_raw_text(b"\xd0\xcf\x11\xe0", "old_resume.doc")
    assert excinfo.value.status_code == 400
    assert "Save As" in excinfo.value.detail


def test_unknown_extension_is_rejected():
    with pytest.raises(HTTPException) as excinfo:
        extract_raw_text(b"data", "resume.txt")
    assert excinfo.value.status_code == 400
