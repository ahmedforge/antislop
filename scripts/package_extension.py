"""Build an allowlisted, reproducible Chrome extension ZIP (Python 3.12)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "background.js", "content.js", "popup.js", "content.css",
    "popup.html", "popup.css", "manifest.json",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="Package for local testing, not store submission")
    args = parser.parse_args()
    origin = os.environ.get("ANTISLOP_API_BASE_URL", "")
    parsed = urlsplit(origin)
    if not args.local and (parsed.scheme != "https" or not parsed.hostname or
                           parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        parser.error("Set ANTISLOP_API_BASE_URL to your deployed HTTPS API origin, or use --local.")
    subprocess.run(["npm", "run", "build", "--", "--release"], cwd=ROOT / "extension", check=True)
    dist = ROOT / "extension" / "dist"
    manifest = json.loads((dist / "manifest.json").read_text())
    package = json.loads((ROOT / "extension" / "package.json").read_text())
    if manifest["version"] != package["version"]:
        raise SystemExit("manifest.json and package.json versions must match")
    if set(path.name for path in dist.iterdir()) != set(FILES):
        raise SystemExit("Unexpected build contents; refusing to package")
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    suffix = "-local" if args.local else ""
    archive = destination / f"antislop-{manifest['version']}{suffix}.zip"
    temporary = archive.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for name in sorted(FILES):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                output.writestr(info, (dist / name).read_bytes())
        with zipfile.ZipFile(temporary) as output:
            if output.testzip() is not None:
                raise SystemExit("ZIP integrity check failed")
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
    print(f"Packaged {archive}\nSHA256 {digest}")


if __name__ == "__main__":
    main()
