#!/usr/bin/env python3
"""Isolated Juno level probes; no edits to the Blue project or filter code.

python3 experiments/measure_juno60_levels.py
The reference is the local native plugin, with its search path isolated.
These are software measurements, not recordings of original hardware.
"""
from research_paths import PLUGIN, RESULTS
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent / "tests"))
from check_juno60vcf import csd, samples, rms


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=PLUGIN)
    parser.add_argument("--output", type=Path, default=RESULTS / "juno60_levels_calibrated")
    args = parser.parse_args()
    plugin = args.plugin.resolve()
    assert plugin.is_file(), plugin
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix="juno60-levels-") as temporary:
        directory = Path(temporary)
        env = dict(os.environ, CS_USER_PLUGINDIR=temporary,
                   OPCODE7DIR=temporary, OPCODE7DIR64=temporary)

        def probe(name, source, cutoff, resonance, scale=1, hpf=0):
            body = (source + f"\naFiltered = juno60vcf(aIn, {cutoff}, {resonance}, 1, {scale})\n"
                    + (f"aOut = zdf1pole(aFiltered, {hpf}, 1)" if hpf else "aOut = aFiltered"))
            path, output = directory / "probe.csd", directory / "probe.wav"
            path.write_text(csd(body, duration=1))
            result = subprocess.run(["csound", f"--opcode-lib={plugin}", "-W",
                                     "--format=double", "-o", str(output), str(path)],
                                    capture_output=True, text=True, timeout=30, env=env)
            assert result.returncode == 0, result.stderr
            values, rate = samples(output)
            assert values and all(math.isfinite(x) for x in values), name
            values = values[rate//2:rate]  # controls/converters settled; no envelope
            row = dict(name=name, cutoff_hz=cutoff, resonance=resonance,
                       feedback_scale=scale, post_hpf_hz=hpf,
                       peak=max(abs(x) for x in values), peak_to_peak=max(values)-min(values),
                       rms=rms(values))
            rows.append(row)
            print(f"{name}: p-p {row['peak_to_peak']:.6g}, RMS {row['rms']:.6g}")
            return row

        pulse = probe("pulse_reference", "aIn = vco2(1, cpsmidinn(60), 2, .5)", 23520, 0)
        probe("saw_reference", "aIn = vco2(1, cpsmidinn(60))", 23520, 0)
        probe("noise_reference", "aIn = random:a(-1, 1)", 23520, 0)
        oscillation = probe("self_oscillation_reference", "aIn = 0", 248, 1)
        ratio = pulse["peak_to_peak"] / oscillation["peak_to_peak"]
        assert abs(20*math.log10(ratio)) < .5, ratio
        assert math.isclose(oscillation["peak_to_peak"], 2, rel_tol=.01)
        matched = probe("self_oscillation_pp_matched", "aIn = 0", 248, 1, ratio)
        assert math.isclose(matched["peak_to_peak"], pulse["peak_to_peak"], rel_tol=.001)

        # Juno-60 HPF first-order approximation, ignoring switch resistance,
        # finite OTA input impedance, and the common input coupling capacitor.
        resistance = 1 / (1/470000 + 1/33000)
        for mode, capacitance in enumerate((.022e-6, .01e-6, .0047e-6), 1):
            hpf = 1 / (2*math.pi*resistance*capacitance)
            row = probe(f"self_oscillation_hpf_{mode}", "aIn = 0", 248, 1, hpf=hpf)
            expected = 248 / math.hypot(248, hpf)
            assert math.isclose(row["rms"] / oscillation["rms"], expected, rel_tol=.01)

    write_csv(args.output / "calibration.csv", rows)
    curves = []
    for panel in (0, 1.5, 2, 5, 10):
        previous, linear = 10**((6*panel-60)/20), panel/10
        current = linear / (1+(50/47)*linear*(1-linear))
        curves.append(dict(panel=panel, previous_gain=previous, current_gain=current, unloaded_linear_cv=linear,
                           change_db=20*math.log10(current/previous) if current else "exact off"))
    write_csv(args.output / "source_controls.csv", curves)
    metadata = dict(sample_rate=48000, ksmps=32, duration_seconds=1,
                    analysis_seconds=[.5, 1], input_drive=1, oversampling=4,
                    warm_start=1, vca_envelope="absent; identical unity gain for all probes",
                    chorus="absent", seed=1234,
                    pulse_to_oscillation_pp_db=20*math.log10(ratio),
                    pp_matched_feedback_scale=ratio,
                    hpf_approximation="one pole, R=470k||33k; bilinear zdf1pole highpass",
                    source_control="50k linear pot with 47k wiper load; bias offsets omitted",
                    plugin=plugin.name,
                    plugin_sha256=hashlib.sha256(plugin.read_bytes()).hexdigest(),
                    native_source_sha256=hashlib.sha256((PROJECT.parent / "src/juno60vcf.c").read_bytes()).hexdigest(),
                    csd_sha256=hashlib.sha256((PROJECT / "fixtures/Juno60Filter.csd").read_bytes()).hexdigest())
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2)+"\n")
    print(f"Pulse/self-oscillation discrepancy: {20*math.log10(ratio):.3f} dB")


if __name__ == "__main__":
    main()
