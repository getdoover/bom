"""Download the newest BOM product files from an FTP server."""

import ftplib
import io


def latest_file(names: list[str], prefix: str) -> str | None:
    # BOM names timestamped products PREFIX_YYYYMMDDHHMMSS.ext; the newest sorts last.
    matches = [n for n in names if n.startswith(prefix + "_")]
    return max(matches) if matches else None


def download_latest(
    host: str,
    username: str,
    password: str,
    directory: str,
    prefixes: list[str],
    timeout: float = 60,
) -> dict[str, str]:
    """Return {file name: text} for the newest file matching each prefix."""
    files = {}
    with ftplib.FTP(host, timeout=timeout) as ftp:
        ftp.login(username or "anonymous", password)
        ftp.cwd(directory)
        names = [n.rsplit("/", 1)[-1] for n in ftp.nlst()]
        for prefix in prefixes:
            name = latest_file(names, prefix)
            if name is None or name in files:
                continue
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {name}", buf.write)
            files[name] = buf.getvalue().decode("latin-1")
    return files
