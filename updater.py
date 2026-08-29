"""
Self-update support for the DavyJones EDMC plugin.

Checks the GitHub Releases API for a newer tagged release and, if found, downloads the
release asset built by .github/workflows/release.yml and extracts it over the plugin
folder so the update takes effect on the next EDMC restart. Built on urllib only — this
plugin has no dependency on `requests` / `semantic_version`.

A file named disable-auto-update.txt in the plugin folder disables all of this, which is
useful for local development against an unpacked checkout.
"""

import json
import logging
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
from urllib import request as urlrequest

logger = logging.getLogger("DavyJones.updater")

GITHUB_REPO = "ScarletTiberius/DavyJonesEDMC"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
HTTP_TIMEOUT = 15  # seconds

UPDATES_DIRNAME = "updates"
BACKUPS_DIRNAME = "backups"
DISABLE_FILE = "disable-auto-update.txt"
BACKUPS_KEEP = 3

_EXCLUDE_DIR_NAMES = {UPDATES_DIRNAME, BACKUPS_DIRNAME, "__pycache__", ".git"}
_EXCLUDE_FILE_SUFFIXES = (".pyc", ".pyo")


@dataclass
class UpdateResult:
    checked_ok: bool = False
    update_found: bool = False
    installed: bool = False
    remote_version: Optional[str] = None
    release_url: Optional[str] = None
    error: Optional[str] = None


def _parse_version(v: str) -> Tuple[int, ...]:
    """Best-effort parse of a version-ish string: 'v1.2.3-beta' -> (1, 2, 3).
    Missing or non-numeric segments become 0 so comparisons never raise."""
    v = v.strip().lstrip("vV")
    v = v.split("+", 1)[0].split("-", 1)[0]  # drop build/prerelease suffix
    parts = []
    for chunk in v.split("."):
        m = re.match(r"\d+", chunk)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts) or (0,)


def _version_gt(a: Tuple[int, ...], b: Tuple[int, ...]) -> bool:
    length = max(len(a), len(b))
    a = a + (0,) * (length - len(a))
    b = b + (0,) * (length - len(b))
    return a > b


def _http_get_json(url: str, user_agent: str) -> dict:
    req = urlrequest.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": user_agent},
        method="GET",
    )
    with urlrequest.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest_path: str, user_agent: str) -> None:
    req = urlrequest.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/octet-stream"},
        method="GET",
    )
    tmp_path = dest_path + ".part"
    with urlrequest.urlopen(req, timeout=HTTP_TIMEOUT) as resp, open(tmp_path, "wb") as f:
        shutil.copyfileobj(resp, f, length=65536)
    os.replace(tmp_path, dest_path)


def _make_backup(plugin_dir: str, backups_dir: str) -> None:
    """Zip the current plugin folder into backups/ before overwriting it, keeping the
    newest BACKUPS_KEEP archives."""
    os.makedirs(backups_dir, exist_ok=True)
    backup_path = os.path.join(backups_dir, datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + ".zip")

    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(plugin_dir):
            dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIR_NAMES and not d.startswith(".")]
            for name in files:
                if name.endswith(_EXCLUDE_FILE_SUFFIXES):
                    continue
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, plugin_dir))

    backups = sorted(
        (os.path.join(backups_dir, f) for f in os.listdir(backups_dir) if f.endswith(".zip")),
        key=os.path.getmtime,
    )
    for old in backups[:-BACKUPS_KEEP]:
        try:
            os.remove(old)
        except OSError:
            logger.warning(f"Could not remove old backup {old}")


def _extract_over(zip_path: str, plugin_dir: str) -> None:
    """Extract the downloaded release zip over plugin_dir.

    The release workflow packs everything under a single top-level `DavyJones/` folder
    (and a GitHub-generated source zipball would do the same with a repo/sha-named
    folder), so strip whatever common top-level folder is present before extracting.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        prefix = ""
        if names:
            first_parts = names[0].split("/", 1)
            if len(first_parts) == 2 and all(n.split("/", 1)[0] == first_parts[0] for n in names):
                prefix = first_parts[0] + "/"

        for member in zf.namelist():
            rel = member[len(prefix):] if prefix and member.startswith(prefix) else member
            if not rel or rel.endswith("/"):
                continue
            target = os.path.join(plugin_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def check_and_update(plugin_dir: str, current_version: str, user_agent: str) -> UpdateResult:
    """Synchronous — call from a background thread, never from the Tk main loop.

    Checks GitHub releases/latest; if it's newer than current_version, downloads and
    extracts it over plugin_dir. The running process keeps the old code in memory, so
    this only takes effect the next time EDMC starts.
    """
    result = UpdateResult()

    if os.path.exists(os.path.join(plugin_dir, DISABLE_FILE)):
        logger.info(f"Auto-update disabled ({DISABLE_FILE} present in plugin folder)")
        result.checked_ok = True
        return result

    try:
        data = _http_get_json(RELEASES_API_URL, user_agent)
    except Exception as e:
        logger.warning(f"Update check failed: {e}")
        result.error = str(e)
        return result

    result.checked_ok = True

    if data.get("draft") or data.get("prerelease"):
        return result

    tag = data.get("tag_name") or ""
    result.release_url = data.get("html_url") or RELEASES_PAGE_URL

    if not tag or not _version_gt(_parse_version(tag), _parse_version(current_version)):
        return result

    result.update_found = True
    result.remote_version = tag.lstrip("vV")

    assets = data.get("assets") or []
    download_url = None
    if assets and assets[0].get("browser_download_url"):
        download_url = assets[0]["browser_download_url"]
    elif data.get("zipball_url"):
        download_url = data["zipball_url"]

    if not download_url:
        logger.warning("Newer release found but it has no downloadable asset")
        return result

    updates_dir = os.path.join(plugin_dir, UPDATES_DIRNAME)
    backups_dir = os.path.join(plugin_dir, BACKUPS_DIRNAME)

    try:
        os.makedirs(updates_dir, exist_ok=True)
        zip_path = os.path.join(updates_dir, "latest.zip")
        _download(download_url, zip_path, user_agent)
        _make_backup(plugin_dir, backups_dir)
        _extract_over(zip_path, plugin_dir)
        result.installed = True
        logger.info(f"Downloaded and installed DavyJones {result.remote_version} — restart EDMC to apply")
    except Exception as e:
        logger.exception("Auto-update download/install failed")
        result.error = str(e)

    return result
