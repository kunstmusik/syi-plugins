#!/usr/bin/env python3
"""Isolated Csound filter probes; no Blue edits or audio-device output.

Run: python3 experiments/filter_compare.py
CSV is written to stdout; save generated reports outside the source tree.
Requires Csound 7. Uses only the Python standard library. WAVs are temporary.
"""
import csv
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

SR = 44100
DURATION = 3


def read_float_wav(path):
    data = path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    chunks = {}
    pos = 12
    while pos + 8 <= len(data):
        name, size = struct.unpack_from("<4sI", data, pos)
        chunks[name] = data[pos + 8:pos + 8 + size]
        pos += 8 + size + (size % 2)
    fmt, channels, rate = struct.unpack_from("<HHI", chunks[b"fmt "])
    bits = struct.unpack_from("<H", chunks[b"fmt "], 14)[0]
    assert (fmt, channels, rate, bits) == (3, 1, SR, 64)
    raw = chunks[b"data"]
    samples = struct.unpack(f"<{len(raw) // 8}d", raw)
    assert abs(len(samples) - SR * DURATION) <= 64
    assert all(math.isfinite(x) for x in samples), "Nonfinite filter output"
    return samples


def rms(samples, start, stop):
    window = samples[int(start * SR):int(stop * SR)]
    return math.sqrt(sum(x * x for x in window) / len(window))


def probe(directory, model, resonance, stimulus, cutoff=1000):
    filters = {
        "zdfladder": f"zdfladder(ain, {cutoff}, {0.5 + 24.5 * resonance})",
        "diodeladder": f"diodeladder(ain, {cutoff}, {17 * resonance}, 1, 1)",
        "moogladder": f"moogladder(ain, {cutoff}, {resonance})",
    }
    sources = {
        "zero": "ain = 0",
        "burst": "aGate linseg 1, 0.02, 1, 1/sr, 0\nain = random:a(-0.01, 0.01) * aGate",
        "floor": "ain = random:a(-1, 1) * ampdbfs(-75)",
        "sine": "ain oscili 0.01, 100, 1",
    }
    csd = directory / "probe.csd"
    wav = directory / "probe.wav"
    csd.write_text(f"""<CsoundSynthesizer>
<CsOptions>
-d -m0
</CsOptions>
<CsInstruments>
sr = {SR}
ksmps = 32
nchnls = 1
0dbfs = 1
seed 1234
instr 1
{sources[stimulus]}
aout = {filters[model]}
out aout
endin
</CsInstruments>
<CsScore>
f1 0 16384 10 1
i1 0 {DURATION}
e
</CsScore>
</CsoundSynthesizer>
""")
    result = subprocess.run(
        ["csound", "-W", "--format=double", "-o", str(wav), str(csd)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    samples = read_float_wav(wav)
    early = rms(samples, 0.2, 0.4)
    late = rms(samples, 2.8, 3)
    delta = 20 * math.log10(late / early) if early and late else None
    gain = late / (0.01 / math.sqrt(2)) if stimulus == "sine" else None
    ring_hz = None
    if stimulus in ("burst", "floor") and late > 1e-8:
        tail = samples[int(2.8 * SR):]
        crossings = [i - tail[i] / (tail[i + 1] - tail[i])
                     for i in range(len(tail) - 1) if tail[i] <= 0 < tail[i + 1]]
        if len(crossings) > 1:
            ring_hz = SR * (len(crossings) - 1) / (crossings[-1] - crossings[0])
    onset = None
    if model == "moogladder" and stimulus == "floor":
        onset = next((t / 100 for t in range(300)
                      if rms(samples, t / 100, (t + 1) / 100) >= 0.9 * late), None)
    if stimulus == "zero":
        assert max(abs(x) for x in samples) == 0
    return [model, resonance, stimulus, cutoff, early, late,
            delta, max(abs(x) for x in samples), gain, ring_hz, onset]


def main():
    writer = csv.writer(sys.stdout)
    writer.writerow(["model", "resonance_fraction", "stimulus", "cutoff_hz",
                     "rms_0.2_0.4s", "rms_2.8_3s", "change_db", "peak", "sine_gain",
                     "tail_crossing_hz", "first_10ms_window_at_90pct_tail_rms_s"])
    with tempfile.TemporaryDirectory(prefix="juno-filter-") as directory:
        for model in ("zdfladder", "diodeladder", "moogladder"):
            writer.writerow(probe(Path(directory), model, 1, "zero"))
            for resonance in (0.98, 1, 1.02, 1.05):
                writer.writerow(probe(Path(directory), model, resonance, "burst"))
            for resonance in (0, 0.8):
                writer.writerow(probe(Path(directory), model, resonance, "sine"))
            for cutoff in (248, 1000):
                writer.writerow(probe(Path(directory), model, 1.05, "floor", cutoff))


if __name__ == "__main__":
    main()
