"""
Import CC0 sound files from a downloaded pack (v0.24.0 spec §8.2).

    python -I scripts/import_sounds.py --archive <zip> --pack "RPG Audio" --page <asset page url>
        --member <path in zip> [--member ...] --licence-member License.txt --downloaded YYYY-MM-DD
        [--pack-version 1.0] --to <sounds dir>

Reads ONLY the named members (the archive is untrusted data: nothing else is extracted, nothing is run), copies
each byte-for-byte to <to>/files/kenney/<pack-slug>/<basename lower-cased>, copies the licence once to
<to>/LICENSES/kenney-<pack-slug>.txt (one per pack: each pack's own text), and appends one PROVENANCE.yaml row
per file. Pure Python: Windows and Linux alike.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

import yaml

AUTHOR = "Kenney (www.kenney.nl)"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True)
    ap.add_argument("--pack", required=True)
    ap.add_argument("--page", required=True)
    ap.add_argument("--member", action="append", required=True)
    ap.add_argument("--licence-member", required=True)
    ap.add_argument("--downloaded", required=True)
    ap.add_argument("--pack-version", default="")
    ap.add_argument("--to", required=True)
    args = ap.parse_args(argv)
    archive = Path(args.archive)
    to = Path(args.to)
    slug = re.sub(r"[^a-z0-9]+", "-", args.pack.lower()).strip("-")
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    prov_path = to / "PROVENANCE.yaml"
    prov = yaml.safe_load(prov_path.read_text(encoding="utf-8")) if prov_path.is_file() else None
    rows = (prov or {}).get("files", [])
    with zipfile.ZipFile(archive) as zf:
        licence = to / "LICENSES" / f"kenney-{slug}.txt"
        licence.parent.mkdir(parents=True, exist_ok=True)
        licence.write_bytes(zf.read(args.licence_member))
        for member in args.member:
            name = PurePosixPath(member).name
            if not name.lower().endswith(".ogg") or ".." in PurePosixPath(member).parts:
                raise SystemExit(f"refused member {member!r}: not a plain .ogg")
            data = zf.read(member)
            rel = f"files/kenney/{slug}/{name.lower()}"
            target = to / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            row = {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "author": AUTHOR,
                   "pack": args.pack, "source_url": args.page, "archive": archive.name, "archive_sha256": archive_sha,
                   "member": member, "licence": "CC0-1.0", "licence_file": f"LICENSES/kenney-{slug}.txt",
                   "downloaded": args.downloaded, "imported": dt.date.today().isoformat()}
            if args.pack_version:
                row["pack_version"] = args.pack_version
            rows = [r for r in rows if r["path"] != rel] + [row]
    header = "# Every shipped sound file (v0.24.0 spec §8.2). Written by scripts/import_sounds.py; do not hand-edit.\n"
    prov_path.write_text(header + yaml.safe_dump({"files": sorted(rows, key=lambda r: r["path"])}, sort_keys=False),
                         encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
