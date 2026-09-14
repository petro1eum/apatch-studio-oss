"""Build-time packaging of the prebuilt client; consumer installs never run Node."""
from __future__ import annotations

import re
from pathlib import Path

from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parents[1]


def _built_frontend() -> Path:
    root = ROOT / "frontend" / "dist"
    message = "Frontend build missing or incomplete; run npm --prefix frontend run build before packaging."
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(message)
    index = root / "index.html"
    if not index.is_file() or not (root / "theme-init.js").is_file():
        raise RuntimeError(message)
    html = index.read_text(encoding="utf-8")
    references = re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', html)
    if ("__APATCH_STUDIO_SESSION__" not in html
            or not any(ref.startswith("/assets/") and ref.endswith(".js") for ref in references)):
        raise RuntimeError(message)
    for reference in references:
        if not reference.startswith(("/assets/", "/theme-init.js")):
            raise RuntimeError("The packaged frontend must use only its own local assets.")
        path = root / reference.removeprefix("/")
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            raise RuntimeError(message)
    if any(path.is_symlink() for path in root.rglob("*")):
        raise RuntimeError("The packaged frontend must not contain symbolic links.")
    return root


class BuildWithFrontend(build_py):
    def run(self):
        frontend = _built_frontend()
        super().run()
        self.copy_tree(str(frontend), str(Path(self.build_lib) / "apatch_studio" / "_web"))


class SourceWithFrontend(sdist):
    def run(self):
        _built_frontend()
        super().run()
