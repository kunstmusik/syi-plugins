"""Check that research inputs, documentation and plugin paths are self-contained."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

plugin = Path(sys.argv[1]).resolve()
research = Path(__file__).resolve().parents[1] / "research"
for path in research.rglob("*"):
    if not path.is_file() or "__pycache__" in path.parts:
        continue
    assert path.suffix not in (".wav", ".pyc"), path
    text = path.read_text()
    assert not re.search(r"/Users/|~/work/|/var/folders/|/tmp|rhythmic|src/build", text), path
    if path.suffix == ".py":
        ast.parse(text, filename=str(path))
    elif path.suffix == ".json":
        json.loads(text)
    elif path.suffix == ".md":
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if not link.startswith(("https:", "http:", "#", "mailto:")):
                assert not Path(link).is_absolute(), (path, link)
                assert (path.parent / link.split("#", 1)[0]).exists(), (path, link)

fixture = ET.parse(research / "fixtures/voice.blue").getroot()
assert len(fixture.findall(".//instrumentAssignment")) == 6
assert {child.tag for child in fixture} == {"projectProperties", "arrangement"}
assert not (research / "src").exists()

with tempfile.TemporaryDirectory() as directory:
    code = (f"import sys; sys.path.insert(0, {str(research / 'experiments')!r}); "
            "from research_paths import PLUGIN; print(PLUGIN)")
    result = subprocess.run([sys.executable, "-c", code], cwd=directory,
                            env=dict(os.environ, JUNO60VCF_PLUGIN=str(plugin)),
                            capture_output=True, text=True, check=True)
    assert Path(result.stdout.strip()) == plugin
print("Research inputs, links, syntax and plugin resolution passed.")
