"""Brand typography, embedded rather than linked.

The MinIO presentation template specifies Geist -- Semi Bold for titles, Normal for
body -- and treats the typeface as brand-approved rather than optional. Naming it in
a font stack would only help viewers who happen to have it installed, so the variable
woff2 is vendored under ``assets/`` and inlined as a data URI at render time.

Two constraints make inlining the right call rather than a nicety:

* the report has to open from disk with no network, so a CDN link would silently
  fall back to a system face on the machines that matter most;
* it is emailed around, so the file must carry everything it needs.

Cost is 52KB of woff2 (~70KB base64) against a multi-megabyte report. Geist is
licensed under the SIL Open Font License, which permits embedding; the licence
travels with the fonts in ``assets/LICENSE-Geist.txt``.
"""

from __future__ import annotations

import base64
import functools
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"

#: Variable fonts, so one file covers every weight the report uses.
FACES = {
    "Geist": ASSETS / "Geist-Variable.woff2",
    "Geist Mono": ASSETS / "GeistMono-Variable.woff2",
}

#: Stacks referenced by the stylesheet. Geist first, then the same system fallbacks
#: the report used before, so a missing asset degrades rather than breaks.
SANS = ('"Geist",ui-sans-serif,-apple-system,BlinkMacSystemFont,'
        '"Segoe UI",Roboto,sans-serif')
MONO = '"Geist Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'


@functools.lru_cache(maxsize=None)
def _data_uri(path: Path) -> str | None:
    try:
        return "data:font/woff2;base64," + base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return None


def face_rules() -> str:
    """@font-face declarations, or "" if the assets are missing.

    Returning empty rather than raising keeps the report generating on a checkout
    without the binaries -- the stacks above fall back to system faces on their own.
    """
    rules = []
    for family, path in FACES.items():
        uri = _data_uri(path)
        if not uri:
            continue
        rules.append(
            "@font-face{"
            f'font-family:"{family}";'
            f"src:url({uri}) format('woff2');"
            "font-weight:100 900;"       # variable: one file, every weight
            "font-style:normal;"
            "font-display:swap;"
            "}"
        )
    return "\n".join(rules)


def available() -> bool:
    return all(_data_uri(p) for p in FACES.values())
