#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Generate OTA manifest for pico-hk")
    parser.add_argument("--base-url", required=True, help="Base URL where release files are hosted")
    parser.add_argument("--version", required=True, help="Release version string")
    parser.add_argument("--output", default="manifest.json", help="Manifest output path")
    parser.add_argument(
        "--files",
        nargs="+",
        default=[
            "main.py",
            "wifi.py",
            "cloud_client.py",
            "local_server.py",
            "access_point.py",
            "pn532.py",
            "uart.py",
            "sh1107.py",
            "ota.py",
            "version.py",
        ],
        help="Repo-relative files to include",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    base_url = args.base_url.rstrip("/")
    manifest = {
        "version": args.version,
        "min_updater_version": 1,
        "entrypoint": "main.py",
        "files": [],
    }

    for rel_path in args.files:
        path = repo_root / rel_path
        if not path.is_file():
            raise SystemExit("Missing file: {}".format(rel_path))

        manifest["files"].append(
            {
                "path": rel_path,
                "url": "{}/{}".format(base_url, rel_path),
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        )

    output_path = repo_root / args.output
    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
