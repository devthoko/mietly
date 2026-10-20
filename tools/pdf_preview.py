#!/usr/bin/env python3
"""Entwicklungshilfe: rendert die Seiten eines PDFs als PNG nach /tmp (benötigt pypdfium2)."""
import sys

import pypdfium2 as pdfium

pdf = pdfium.PdfDocument(sys.argv[1])
for i in range(len(pdf)):
    out = f"/tmp/page{i + 1}.png"
    pdf[i].render(scale=1.4).to_pil().save(out)
    print(out)
