#!/usr/bin/env python3
"""Probe instrument 6 factory presets; all audio/CSD files are temporary.

python3 experiments/check_juno60_patches.py --patches 74 78
"""
from research_paths import PLUGIN
import argparse
import csv
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
CALLS = {
    "current": None,
    "old_q": "asig = juno60vcf(asig, acutoff, a(0.5 + kResonance * 24.5), a(1))",
    "normalized": "asig = juno60vcf(asig, acutoff, kResonance, 1)",
    "cold": "asig = juno60vcf(asig, acutoff, kResonance, 1, 1, 2, 0)",
    "seeded": "asig = juno60vcf(asig + random:a(-1, 1) * ampdbfs(-75), acutoff, kResonance, 1)",
}


def read_taps(path):
    data = path.read_bytes()
    pos, chunks = 12, {}
    while pos + 8 <= len(data):
        name, size = struct.unpack_from("<4sI", data, pos)
        chunks[name] = data[pos + 8:pos + 8 + size]
        pos += 8 + size + size % 2
    fmt, channels, rate = struct.unpack_from("<HHI", chunks[b"fmt "])
    bits = struct.unpack_from("<H", chunks[b"fmt "], 14)[0]
    assert (fmt, channels, bits) == (3, 3, 64)
    raw = chunks[b"data"]
    values = struct.unpack(f"<{len(raw)//8}d", raw)
    assert all(math.isfinite(x) for x in values), "nonfinite output"
    return [values[channel::3] for channel in range(3)], rate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--patches", nargs="*", type=int)
    parser.add_argument("--modes", nargs="+", choices=CALLS,
                        default=["current", "normalized", "cold"])
    parser.add_argument("--seed-db", type=float, default=-75,
                        help="experimental input noise gain; not hardware calibration")
    parser.add_argument("--plugin", type=Path, default=PLUGIN)
    args = parser.parse_args()
    root = ET.parse(PROJECT / "fixtures/voice.blue").getroot()
    instrument = root.find(".//instrumentAssignment[@arrangementId='6']/instrument")
    assert instrument is not None
    voice = instrument.findtext("instrumentText")
    # Exercise the common output stage after the voice sum. Chorus is bypassed
    # here so source/filter/HPF/patch-LEVEL calibration is measured independently.
    output_stage = instrument.findtext("alwaysOnInstrumentText").split(
        "; CPU voice sum", 1)[1].split("if(<chorus_mode>", 1)[0]
    dropdowns = {}
    for widget in instrument.findall(".//bsbObject"):
        items = widget.findall("bsbDropdownItemList/bsbDropdownItem")
        if items:
            dropdowns[widget.findtext("objectName")] = {
                "id:" + item.get("uniqueId"):item.findtext("value") for item in items}
    presets = []
    for preset in instrument.findall(".//presetGroup[@name='Factory']/preset"):
        number = int(preset.get("name").split()[0])
        if args.patches and number not in args.patches:
            continue
        settings = {}
        for setting in preset.findall("setting"):
            key, value = setting.get("name"), setting.text
            if value.startswith("id:"):
                value = dropdowns[key][value]
            else:
                value = {"true":"1", "false":"0"}.get(value, value)
            settings[key] = value
        presets.append((number, preset.get("name"), settings))
    assert presets, "factory preset group not found"
    rate = int(root.findtext("projectProperties/sampleRate"))
    block = int(root.findtext("projectProperties/ksmps"))
    rows = []
    with tempfile.TemporaryDirectory(prefix="juno60-patches-") as temp:
        directory = Path(temp)
        env = dict(os.environ, CS_USER_PLUGINDIR=str(directory),
                   OPCODE7DIR=str(directory), OPCODE7DIR64=str(directory))
        for number, name, settings in presets:
            for mode in args.modes:
                call = CALLS[mode]
                if mode == "seeded":
                    call = call.replace("ampdbfs(-75)", f"ampdbfs({args.seed_db})")
                text, count = re.subn(r"^asig = juno60vcf\(.*$",
                                      lambda match: "aPreVcf = asig\n" +
                                      (call or match.group()) + "\naPostVcf = asig",
                                      voice, flags=re.M)
                assert count == 1, "expected one native filter call"
                text = text.replace("blueMixerOut asig, asig",
                                    "gaVoices += asig\nout(aPreVcf, aPostVcf, a(0))")
                text = text.replace("<INSTR_ID>", "6")
                post = "aLeft = gaVoices\naRight = gaVoices\n; CPU voice sum" + output_stage
                post += "gaVoices = 0\nout(a(0), a(0), aLeft)"
                for key, value in settings.items():
                    text = text.replace(f"<{key}>", value)
                    post = post.replace(f"<{key}>", value)
                assert not re.findall(r"<[A-Za-z_]\w*>", text+post), "unresolved panel placeholder"
                csd = f"""<CsoundSynthesizer>
<CsOptions>
-d -m0 --sample-accurate
</CsOptions>
<CsInstruments>
sr = {rate}
ksmps = {block}
nchnls = 3
0dbfs = 1
seed 1234
gaVoices init 0
instr Lfo
  kRate = 0.3 * pow(20/0.3, {settings['lfo_rate']} / 10)
  kLfo = lfo:k(1, kRate, 1)
  chnset(kLfo, "jno60_lfo_6")
endin
instr Voice
{text}
endin
instr Output
{post}
endin
</CsInstruments>
<CsScore>
i "Lfo" 0 3
i "Voice" 0 2 60 0
i "Output" 0 3
e
</CsScore>
</CsoundSynthesizer>
"""
                source, wav = directory / "probe.csd", directory / "probe.wav"
                source.write_text(csd)
                result = subprocess.run(["csound", f"--opcode-lib={args.plugin.resolve()}",
                                         "-W", "--format=double", "-o", str(wav), str(source)],
                                        capture_output=True, text=True, timeout=30, env=env)
                assert result.returncode == 0, result.stderr
                taps, actual_rate = read_taps(wav)
                assert actual_rate == rate
                taps = [tap[:2*rate] for tap in taps]
                row = {"patch":number, "name":name, "mode":mode,
                       "seed_gain_db":args.seed_db if mode == "seeded" else "",
                       "panel_resonance":float(settings["vcf_res"]),
                       "pre_vcf_peak":max(abs(x) for x in taps[0]),
                       "post_vcf_peak":max(abs(x) for x in taps[1]),
                       "post_vca_peak":max(abs(x) for x in taps[2]),
                       "post_vca_rms":math.sqrt(sum(x*x for x in taps[2])/len(taps[2])),
                       "first_above_minus60_db_seconds":next(
                           (index/rate for index, value in enumerate(taps[2])
                            if abs(value) >= .001), "")}
                rows.append(row)
                if args.patches or number in (72, 74, 78):
                    print(f"{name}, {mode}: pre VCF {row['pre_vcf_peak']:.6g}, "
                          f"post VCF {row['post_vcf_peak']:.6g}, "
                          f"post VCA {row['post_vca_peak']:.6g}, "
                          f"first > -60 dBFS {row['first_above_minus60_db_seconds']}", flush=True)
                if number in (72, 74, 78):
                    if mode == "cold":
                        assert row["post_vca_peak"] == 0
                    else:
                        assert row["post_vca_peak"] > 1e-4
                if mode == "seeded" or number not in (72, 74, 78):
                    assert row["post_vca_peak"] > 1e-8, (name, row)
            print(f"PASS: {name}", flush=True)
    if args.csv:
        with args.csv.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    silent = sorted({r["name"] for r in rows
                     if r["mode"] in ("current", "old_q") and r["post_vca_peak"] == 0})
    print("Current/original silent presets:", ", ".join(silent))
    print(f"All {len(presets)} factory patch checks passed.")


if __name__ == "__main__":
    main()
