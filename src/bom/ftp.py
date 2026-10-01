"""Download the newest BOM product files over FTP or SFTP."""

import ftplib
import io
import posixpath

import paramiko

KEY_TYPES = (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey)


def latest_file(names: list[str], prefix: str) -> str | None:
    # BOM names timestamped products PREFIX_YYYYMMDDHHMMSS.ext; the newest sorts
    # last. Products kept as a single file (e.g. IDN60920.xml) are named exactly.
    if prefix in names:
        return prefix
    matches = [n for n in names if n.startswith(prefix + "_")]
    return max(matches) if matches else None


def load_private_key(text: str) -> paramiko.PKey:
    for key_type in KEY_TYPES:
        try:
            return key_type.from_private_key(io.StringIO(text.strip() + "\n"))
        except (paramiko.SSHException, ValueError):
            continue
    raise ValueError("Private key is not a readable Ed25519, ECDSA or RSA key")


def download_latest(
    host: str,
    username: str,
    password: str,
    directory: str,
    prefixes: list[str],
    protocol: str = "FTP",
    private_key: str = "",
    timeout: float = 60,
) -> dict[str, str]:
    """Return {file name: text} for the newest file matching each prefix."""
    if protocol == "SFTP":
        return _download_sftp(host, 22, username, private_key, directory, prefixes, timeout)
    return _download_ftp(host, 21, username, password, directory, prefixes, timeout)


def _download_ftp(host, port, username, password, directory, prefixes, timeout):
    files = {}
    with ftplib.FTP(timeout=timeout) as ftp:
        ftp.connect(host, port)
        ftp.login(username or "anonymous", password)
        ftp.cwd(directory)
        names = [n.rsplit("/", 1)[-1] for n in ftp.nlst()]
        for name in _wanted(names, prefixes):
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {name}", buf.write)
            files[name] = buf.getvalue().decode("latin-1")
    return files


def _download_sftp(host, port, username, private_key, directory, prefixes, timeout):
    files = {}
    with paramiko.SSHClient() as ssh:
        # No host key is pinned in config, so accept the server's key on first use.
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            host,
            port=port,
            username=username,
            pkey=load_private_key(private_key),
            timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        with ssh.open_sftp() as sftp:
            names = sftp.listdir(directory)
            for name in _wanted(names, prefixes):
                buf = io.BytesIO()
                sftp.getfo(posixpath.join(directory, name), buf)
                files[name] = buf.getvalue().decode("latin-1")
    return files


def _wanted(names: list[str], prefixes: list[str]) -> list[str]:
    wanted = (latest_file(names, p) for p in prefixes)
    return list(dict.fromkeys(n for n in wanted if n))
