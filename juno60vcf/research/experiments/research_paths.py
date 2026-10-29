"""Shared locations for research inputs, the project plugin and generated results."""
import os
from pathlib import Path
import sys

RESEARCH = Path(__file__).resolve().parents[1]
ROOT = RESEARCH.parent.parent
suffix = ".dylib" if sys.platform == "darwin" else ".dll" if sys.platform == "win32" else ".so"
PLUGIN = Path(os.environ.get("JUNO60VCF_PLUGIN", ROOT / "build/juno60vcf" / ("juno60vcf" + suffix))).resolve()
RESULTS = ROOT / "build/research-results"
RESULTS.mkdir(parents=True, exist_ok=True)
