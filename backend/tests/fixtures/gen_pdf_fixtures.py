"""Generate the small PDF fixtures used by the pypdfium2 checkpoint tests (A-02).

Run once (`uv run python tests/fixtures/gen_pdf_fixtures.py`); the bytes are committed.
reportlab runs with `invariant=1` so regenerating yields identical bytes.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

OUT = Path(__file__).resolve().parent / "pdf"

# Known geometry for test_bbox_roundtrip_reportlab_fixture.
SIMPLE_LINES = [
    (72, 700, "Machine 21 ran normally through both shifts"),
    (72, 660, "Pressure reading 4.2 noted at 14:00"),
]
SIMPLE_FONT = ("Helvetica", 14)
SIMPLE_PAGE = (595.2756, 841.8898)  # A4 in points


def make_simple() -> None:
    c = Canvas(str(OUT / "simple.pdf"), pagesize=SIMPLE_PAGE, pageCompression=0, invariant=1)
    c.setFont(*SIMPLE_FONT)
    for x, y, text in SIMPLE_LINES:
        c.drawString(x, y, text)
    c.save()


def make_huge_mediabox() -> None:
    # 14400 pt is the PDF 1.7 maximum; at 150 dpi this is ~900 M px, far above the 40 M cap.
    c = Canvas(
        str(OUT / "huge_mediabox.pdf"), pagesize=(14400, 14400), pageCompression=0, invariant=1
    )
    c.setFont("Helvetica", 12)
    c.drawString(72, 14000, "tiny text on a huge page")
    c.save()


def make_surrogate() -> None:
    """Hand-built PDF whose ToUnicode CMap maps code 'A' to U+1F600 (a UTF-16 surrogate pair),
    so PDFium reports two char indices for one code point."""
    stream = b"BT /F1 24 Tf 72 700 Td (xAy) Tj ET"
    cmap = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        b"/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
        b"1 begincodespacerange <00> <FF> endcodespacerange\n"
        b"3 beginbfchar\n<78> <0078>\n<41> <D83DDE00>\n<79> <0079>\nendbfchar\n"
        b"endcmap CMapName currentdict /CMap defineresource pop end end"
    )
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    (OUT / "surrogate.pdf").write_bytes(bytes(out))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make_simple()
    make_huge_mediabox()
    make_surrogate()
    print("fixtures written to", OUT)
