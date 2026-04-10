try:
    import ujson as json
except ImportError:
    import json

try:
    import uos as os
except ImportError:
    import os

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii

from cloud_client import get_json, download_file
from version import APP_VERSION


STATE_PATH = "ota_state.json"
VERSION_PATH = "ota_version.txt"
TMP_SUFFIX = ".new"
BACKUP_SUFFIX = ".bak"
UPDATER_VERSION = 1
PRESERVE_PATHS = {
    "wifi_config.py",
    STATE_PATH,
    VERSION_PATH,
}


def _read_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except OSError:
        return default
    except ValueError:
        return default


def _write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


def _read_text(path, default=""):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return default


def _write_text(path, value):
    with open(path, "w") as f:
        f.write(value)


def get_installed_version():
    stored = _read_text(VERSION_PATH, "")
    return stored or APP_VERSION


def cleanup_staging_files():
    for path in os.listdir():
        if path.endswith(TMP_SUFFIX) or path.endswith(BACKUP_SUFFIX):
            try:
                os.remove(path)
            except OSError:
                pass


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(512)
            if not chunk:
                break
            digest.update(chunk)
    return binascii.hexlify(digest.digest()).decode().lower()


def _get_free_bytes():
    try:
        stat = os.statvfs("/")
        return stat[0] * stat[3]
    except AttributeError:
        return None
    except OSError:
        return None


def _validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")

    version = manifest.get("version", "").strip()
    if not version:
        raise ValueError("Manifest version missing")

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Manifest files missing")

    if int(manifest.get("min_updater_version", 1)) > UPDATER_VERSION:
        raise ValueError("Updater version too old")

    for entry in files:
        path = entry.get("path", "")
        url = entry.get("url", "")
        sha256 = entry.get("sha256", "")
        if not path or "/" in path or path in PRESERVE_PATHS:
            raise ValueError("Unsupported OTA path: {}".format(path))
        if not url or not sha256:
            raise ValueError("Manifest entry incomplete for {}".format(path))

    return version, files


def _enough_space(files):
    free_bytes = _get_free_bytes()
    if free_bytes is None:
        return True

    required = 0
    for entry in files:
        required += int(entry.get("size", 0))

    return free_bytes > (required * 2) + 8192


def check_for_update(manifest_url):
    status_code, status_line, manifest = get_json(manifest_url)
    if not (200 <= status_code < 300):
        raise OSError(status_line)

    version, files = _validate_manifest(manifest)
    current_version = get_installed_version()
    if version == current_version:
        return None
    if not _enough_space(files):
        raise OSError("Not enough free space")
    return manifest


def _mark_state(state, version="", detail=""):
    _write_json(
        STATE_PATH,
        {
            "state": state,
            "version": version,
            "detail": detail,
        },
    )


def _clear_state():
    try:
        os.remove(STATE_PATH)
    except OSError:
        pass


def _replace_file(path):
    tmp_path = path + TMP_SUFFIX
    backup_path = path + BACKUP_SUFFIX

    try:
        os.remove(backup_path)
    except OSError:
        pass

    had_original = True
    try:
        os.rename(path, backup_path)
    except OSError:
        had_original = False

    try:
        os.rename(tmp_path, path)
    except OSError:
        if had_original:
            try:
                os.rename(backup_path, path)
            except OSError:
                pass
        raise

    if had_original:
        try:
            os.remove(backup_path)
        except OSError:
            pass


def stage_update(manifest, progress_cb=None):
    version, files = _validate_manifest(manifest)
    _mark_state("staging", version, "")
    cleanup_staging_files()

    for index, entry in enumerate(files, 1):
        path = entry["path"]
        tmp_path = path + TMP_SUFFIX
        if progress_cb:
            progress_cb("download", path, index, len(files))

        try:
            os.remove(tmp_path)
        except OSError:
            pass

        download_file(entry["url"], tmp_path)
        actual_hash = _sha256_file(tmp_path)
        if actual_hash != entry["sha256"].lower():
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise ValueError("Hash mismatch for {}".format(path))


def commit_update(manifest, progress_cb=None):
    version, files = _validate_manifest(manifest)
    _mark_state("committing", version, "")

    entrypoint = manifest.get("entrypoint", "main.py")
    ordered = [entry for entry in files if entry["path"] != entrypoint]
    ordered.extend(entry for entry in files if entry["path"] == entrypoint)

    for index, entry in enumerate(ordered, 1):
        path = entry["path"]
        if progress_cb:
            progress_cb("commit", path, index, len(ordered))
        _replace_file(path)

    _write_text(VERSION_PATH, version)
    _clear_state()
    cleanup_staging_files()


def recover_if_needed():
    state = _read_json(STATE_PATH, None)
    if not state:
        cleanup_staging_files()
        return None

    cleanup_staging_files()
    _clear_state()
    return state


def perform_update(manifest_url, progress_cb=None):
    manifest = check_for_update(manifest_url)
    if manifest is None:
        return False, "up-to-date"

    version = manifest["version"]
    if progress_cb:
        progress_cb("prepare", version, 0, 0)
    stage_update(manifest, progress_cb=progress_cb)
    commit_update(manifest, progress_cb=progress_cb)
    return True, version
