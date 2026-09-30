"""Look up a river gauge's flood classification levels on BOM's flood-warning maps.

Each state's IDx65xxx.html map pages on the public FTP feed carry a hover popup
per gauge: PopupRiver("name", 'id', 'lat', 'lon', 'level', 'class', 'trend',
'time', 'minor', 'moderate', 'major', ...).
"""

import ftplib
import io
import re

HOST = "ftp.bom.gov.au"
DIRECTORY = "/anon/gen/fwo"

POPUP = re.compile(
    r"PopupRiver\(&quot;.*?&quot;,'(?P<id>\d+)','[^']*','[^']*','[^']*','[^']*',"
    r"'[^']*','[^']*','(?P<minor>[^']*)','(?P<moderate>[^']*)','(?P<major>[^']*)'"
)


def parse_levels(html: str, station_id: str) -> list[float | None] | None:
    """(minor, moderate, major) for the station, or None if it isn't on the page."""
    for m in POPUP.finditer(html):
        if m.group("id") == station_id:
            return [_number(m.group(k)) for k in ("minor", "moderate", "major")]
    return None


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def find_levels(
    station_id: str, letter: str, known_page: str | None = None, timeout: float = 60
) -> tuple[str, list[float | None]] | None:
    """Return (page name, levels), checking known_page first, then every state map page."""
    with ftplib.FTP(HOST, timeout=timeout) as ftp:
        ftp.login()
        ftp.cwd(DIRECTORY)
        pages = [] if known_page is None else [known_page]
        pattern = re.compile(rf"^ID{letter}65\d+\.html$")
        pages += sorted(n for n in ftp.nlst() if pattern.match(n) and n != known_page)
        for page in pages:
            buf = io.BytesIO()
            try:
                ftp.retrbinary(f"RETR {page}", buf.write)
            except ftplib.error_perm:
                continue
            levels = parse_levels(buf.getvalue().decode("latin-1"), station_id)
            if levels is not None:
                return page, levels
    return None
