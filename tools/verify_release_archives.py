"""Verify exactly the two reviewed OSS distributions before install or upload."""

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path


def verify_archives(root: Path, directory: Path, tag: str) -> Path:
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    evidence = json.loads((root / "release/publication.json").read_text())
    if tag != "v" + version or evidence.get("version") != version:
        raise ValueError("release tag, reviewed version and package version must match")
    wheel = f"apatch_studio-{version}-py3-none-any.whl"
    names = [wheel, f"apatch_studio-{version}.tar.gz"]
    rows = evidence["artifacts"]
    if ([row["filename"] for row in rows] != names
            or {path.name for path in directory.iterdir()} != set(names)):
        raise ValueError("expected exactly the reviewed wheel and source distribution")
    for row in rows:
        path = directory / row["filename"]
        if (path.is_symlink() or not path.is_file() or not re.fullmatch("[0-9a-f]{64}", row["sha256"])
                or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]):
            raise ValueError(f"artifact digest mismatch: {path.name}")
    return directory / wheel


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    print(verify_archives(Path(__file__).resolve().parents[1], args.directory, args.tag))
