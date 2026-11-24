"""Check an installed OSS pair from outside its checkout. No account or agent needed."""

import json
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

import apatch

import apatch_studio
from apatch_studio.cli import _parser


class PageAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        url = attrs.get("src") if tag == "script" else attrs.get("href") if tag == "link" else None
        if url and url.startswith("/assets/"):
            self.urls.append(url)


def main():
    packages = Path(sysconfig.get_path("purelib")).resolve()
    for module in (apatch, apatch_studio):
        assert Path(module.__file__).resolve().is_relative_to(packages), "expected installed wheels"
    assert set(_parser()._subparsers._group_actions[0].choices) == {"serve", "enroll", "name-this-machine"}
    with tempfile.TemporaryDirectory() as root:
        workspace = Path(root) / "project"
        env = {"HOME": root, "PATH": os.environ["PATH"]}
        subprocess.run(["git", "init", "-q", str(workspace)], env=env, check=True)
        log = Path(root) / "startup.log"
        with log.open("w") as output:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-u", "-m", "apatch_studio.cli", "serve",
                 "--no-open", "--port", "0", "--workspace", str(workspace)],
                cwd=root, env=env, stdout=output, stderr=output,
            )
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    startup = log.read_text()
                    if proc.poll() is not None:
                        raise RuntimeError(f"Studio exited during startup:\n{startup}")
                    match = re.search(r"^APatch Studio OSS: (http://127\.0\.0\.1:\d+)/$", startup, re.MULTILINE)
                    if match:
                        break
                    time.sleep(0.1)
                else:
                    raise TimeoutError("Studio did not announce a loopback address")
                origin = match[1]
                local = build_opener(ProxyHandler({}))
                with local.open(origin + "/api/v1/health", timeout=10) as response:
                    health = json.load(response)
                assert health["ok"] and health["frontend_ready"] and health["edition"] == "oss"
                with local.open(origin + "/", timeout=10) as response:
                    markup = response.read().decode()
                assert "__APATCH_STUDIO_SESSION__" not in markup
                assets = PageAssets()
                assets.feed(markup)
                assert {Path(url).suffix for url in assets.urls} >= {".js", ".css"}
                for url in assets.urls:
                    with local.open(origin + url, timeout=10) as response:
                        assert response.status == 200 and response.read(1)
                print(f"Studio OSS {health['version']}, Core {apatch.__version__}: "
                      f"serve, health, HTML and {len(assets.urls)} assets OK")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    main()
