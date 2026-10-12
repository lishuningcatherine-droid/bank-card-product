"""PDF → text via pdfplumber."""

from __future__ import annotations

import io

import pdfplumber


def pdf_to_text(data: bytes) -> str:
    out: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)
