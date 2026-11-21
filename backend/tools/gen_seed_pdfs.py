"""Deterministic generator for the authored seed PDF (D-02, skeleton part).

reportlab with invariant=1 and a vendored TTF, so the bytes are identical on every machine.
Run once; the bytes plus an entry in seed/SHA256SUMS are committed and `verify_seed` only checks.

    python -m tools.gen_seed_pdfs          # writes the PDF and refreshes SHA256SUMS
    python -m tools.gen_seed_pdfs --check  # exits 1 when the committed bytes would change
"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

SEED = Path(__file__).resolve().parents[2] / "seed"
FONT = SEED / "fonts" / "Vera.ttf"
REPORT = SEED / "authored" / "reports" / "report_0805.pdf"
SUMS = SEED / "SHA256SUMS"

# Page 1, line 4 is the sentence the reader extracts (PRD Demo 0). Written for the demo.
LINES = [
    "Shift report - written for the demo (synthetic document)",
    "Report date: 06 Aug 2015 09:10",
    "Reporting period: 05 Aug 2015",
    "Machine 21 ran normally through both shifts.",
    "Signed: shift supervisor (synthetic)",
]


def report_bytes() -> bytes:
    pdfmetrics.registerFont(TTFont("Vera", str(FONT)))
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4, invariant=1)
    pdf.setTitle("Shift report (synthetic)")
    pdf.setFont("Vera", 12)
    y = 780.0
    for line in LINES:
        pdf.drawString(72, y, line)
        y -= 24
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


def sums_lines() -> list[str]:
    files = [FONT, REPORT, SEED / "labels.yaml", SEED / "skeleton_case.yaml"]
    return [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(SEED).as_posix()}"
        for p in sorted(files)
    ]


def main(argv: list[str]) -> int:
    data = report_bytes()
    if "--check" in argv:
        return 0 if REPORT.is_file() and REPORT.read_bytes() == data else 1
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_bytes(data)
    SUMS.write_text("\n".join(sums_lines()) + "\n", encoding="utf-8")
    print(f"wrote {REPORT} sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
