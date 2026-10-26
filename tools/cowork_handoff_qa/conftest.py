"""Local candidate and existing Platform verifier; no network or Docker."""
from pathlib import Path
import os
import sys
STUDIO=Path(__file__).resolve().parents[2]
PLATFORM=Path(os.environ.get("COWORK_PLATFORM_SOURCE", str(STUDIO.parent/"platform")))
sys.path[:0]=[str(Path(__file__).resolve().parent),str(STUDIO),str(PLATFORM)]
