#!/usr/bin/env python3
"""Erzeugt statische Assets aus den Quellen (nur bei der Entwicklung nötig).

* static/icons.svg   – SVG-Sprite mit genau den verwendeten Lucide-Icons (ISC-Lizenz)
* static/fonts/*.woff2 – Source Sans 3 und EB Garamond (SIL Open Font License), auf Latin-Zeichen reduziert

Aufruf:  .venv/bin/python tools/build_assets.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPRITE = ROOT / "tools" / "vendor" / "lucide-sprite.svg"


ICON_PATTERNS = [
    re.compile(r"""\{%\s*icon\s+['"]([a-z0-9-]+)['"]"""),
    re.compile(r"""["']icon["']\s*:\s*["']([a-z0-9-]+)["']"""),
]


def used_icons():
    names = set()
    for path in list((ROOT / "templates").rglob("*.html")) + list((ROOT / "apps").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in ICON_PATTERNS:
            names.update(pattern.findall(text))
    return sorted(names)


def build_icons():
    sprite = SPRITE.read_text(encoding="utf-8")
    out = ['<svg xmlns="http://www.w3.org/2000/svg">', "<!-- Lucide Icons, ISC License, https://lucide.dev -->"]
    missing = []
    for name in used_icons():
        m = re.search(rf'<symbol id="{re.escape(name)}">(.*?)</symbol>', sprite, re.S)
        if not m:
            missing.append(name)
            continue
        body = re.sub(r"\s+", " ", m.group(1)).strip()
        out.append(f'<symbol id="{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</symbol>')
    out.append("</svg>")
    (ROOT / "static" / "icons.svg").write_text("\n".join(out), encoding="utf-8")
    print(f"icons.svg: {len(out) - 3} Icons")
    if missing:
        print("FEHLENDE ICONS:", ", ".join(missing))
        return False
    return True


FONTS = {
    # Fließtext: Source Sans 3 (SIL OFL) – freundlich und gut lesbar
    "SourceSans3-Regular.woff2": "/usr/share/fonts/opentype/sourcesans3/SourceSans3-Regular.otf",
    "SourceSans3-It.woff2": "/usr/share/fonts/opentype/sourcesans3/SourceSans3-It.otf",
    "SourceSans3-Semibold.woff2": "/usr/share/fonts/opentype/sourcesans3/SourceSans3-Semibold.otf",
    "SourceSans3-Bold.woff2": "/usr/share/fonts/opentype/sourcesans3/SourceSans3-Bold.otf",
    # Überschriften: EB Garamond (SIL OFL) – elegant, passend zu Hochzeit & Dekoration
    "EBGaramond-Regular.woff2": "/usr/share/fonts/opentype/ebgaramond/EBGaramond12-Regular.otf",
    "EBGaramond-Italic.woff2": "/usr/share/fonts/opentype/ebgaramond/EBGaramond12-Italic.otf",
    "EBGaramond-Bold.woff2": "/usr/share/fonts/opentype/ebgaramond/EBGaramond12-Bold.otf",
}


def build_fonts():
    from fontTools import subset

    target = ROOT / "static" / "fonts"
    target.mkdir(exist_ok=True)
    for old in target.glob("Inter-*.woff2"):
        old.unlink()
    unicodes = "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2190-2199,U+2212,U+2215"
    for name, src in FONTS.items():
        dst = target / name
        subset.main([src, f"--unicodes={unicodes}", "--flavor=woff2", "--layout-features=*", f"--output-file={dst}"])
        print(f"{dst.name}: {dst.stat().st_size // 1024} KB")


if __name__ == "__main__":
    ok = build_icons()
    if "--fonts" in sys.argv:
        build_fonts()
    sys.exit(0 if ok else 1)
