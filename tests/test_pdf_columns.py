"""Tests for two-column PDF extraction.

A sidebar CV read line by line interleaves the columns ("Databricks, Azure Data
Factory, Designation: Automation Solution Architect"). The model then credited
one employer's role and dates to the next employer down.
"""
import os

os.environ.setdefault("ALLOW_ANONYMOUS_AUTH", "true")

from src.app import extract_raw_text  # noqa: E402

PAGE_W, PAGE_H = 612, 792


def _pdf(pages) -> bytes:
    """A minimal PDF; each page is a list of (x, y, text) in points from bottom-left."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        stream = "".join(
            f"BT /F1 9 Tf {x} {y} Td ({t}) Tj ET\n" for x, y, t in lines
        ).encode("latin-1")
        objects.append(b"<< /Length %d >>stream\n%sendstream" % (len(stream), stream))
        content_id = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
            % (PAGE_W, PAGE_H, content_id)
        )
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids))

    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (num, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def _two_column_page(sidebar, main):
    """Sidebar at x=40, main column at x=230, rows aligned side by side."""
    lines = []
    for i, text in enumerate(sidebar):
        lines.append((40, 740 - i * 14, text))
    for i, text in enumerate(main):
        lines.append((230, 741 - i * 14, text))  # baselines deliberately off by 1pt
    return lines


SIDEBAR_1 = [f"Sidebar skill {i}" for i in range(12)]
MAIN_1 = ["Atos Global IT SS Pvt Ltd Apr 2015 - Mar 2024",
          "Designation: Product Owner",
          "Duration: June 2022 - Mar 2024"] + [f"Atos bullet {i}" for i in range(9)]
SIDEBAR_2 = [f"Sidebar certification {i}" for i in range(12)]
MAIN_2 = ["Designation: Automation Solution Architect",
          "Duration: Jan 2020 - May 2022"] + [f"Atos later bullet {i}" for i in range(10)]


def test_columns_are_not_interleaved():
    text = extract_raw_text(_pdf([_two_column_page(SIDEBAR_1, MAIN_1)]), "cv.pdf")
    for line in text.splitlines():
        assert not ("Sidebar" in line and ("Atos" in line or "Designation" in line)), line


def test_main_column_reads_continuously_across_pages():
    """The page-2 sidebar must not land between an employer's page-1 and page-2 roles."""
    pdf = _pdf([_two_column_page(SIDEBAR_1, MAIN_1), _two_column_page(SIDEBAR_2, MAIN_2)])
    text = extract_raw_text(pdf, "cv.pdf")
    product_owner = text.index("Designation: Product Owner")
    architect = text.index("Designation: Automation Solution Architect")
    assert "Sidebar" not in text[product_owner:architect]
    assert text.index("Sidebar certification 0") < product_owner


def test_single_column_page_is_read_as_is():
    lines = [(40, 740 - i * 14, f"Full width line number {i} that runs right across the page body text")
             for i in range(25)]
    text = extract_raw_text(_pdf([lines]), "cv.pdf")
    assert "Full width line number 0 that runs right across the page body text" in " ".join(text.split())
