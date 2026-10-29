#!/usr/bin/env python3
"""Render instrument 6's actual voice, common output stage and chorus in isolation."""
from research_paths import PLUGIN, RESULTS
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from check_juno60_startup import read_stereo

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=RESULTS / "juno60_voice_calibrated.csv")
    parser.add_argument("--all-presets", action="store_true", help="Also render every custom preset on its own synth")
    args = parser.parse_args()
    root = ET.parse(PROJECT / "fixtures/voice.blue").getroot()
    assignments = root.findall(".//instrumentAssignment")
    assert all(a.findtext("instrument/name") == "JNO60" for a in assignments)
    instrument = root.find(".//instrumentAssignment[@arrangementId='6']/instrument")
    dropdowns = {}
    for widget in instrument.findall(".//bsbObject"):
        items = widget.findall("bsbDropdownItemList/bsbDropdownItem")
        if items:
            dropdowns[widget.findtext("objectName")] = {
                # Blue's automated dropdown parameters use the selected index;
                # chorus entries retain literal "Value" as their unused text.
                "id:"+item.get("uniqueId"): str(index) for index, item in enumerate(items)}
    presets = []
    for preset in instrument.findall(".//presetGroup[@name='Factory']/preset"):
        values = {}
        for entry in preset.findall("setting"):
            key, value = entry.get("name"), entry.text
            if value.startswith("id:"):
                value = dropdowns[key][value]
            values[key] = {"true": "1", "false": "0"}.get(value, value)
        presets.append((preset.get("name"), values))
    assert len(presets) == 56
    definitions = []
    for udo in instrument.findall("opcodeList/udo"):
        outputs = udo.findtext("outTypes").replace(",", "").replace(" ", "")
        outputs = "("+",".join(outputs)+")" if len(outputs) > 1 else outputs
        definitions.append(f"opcode {udo.findtext('opcodeName')}({udo.findtext('inputArguments')}):{outputs}\n"
                           + udo.findtext("codeBody") + "\nendop\n")
    voice = instrument.findtext("instrumentText").replace(
        "blueMixerOut asig, asig", "gaLeft += asig\ngaRight += asig")
    post = instrument.findtext("alwaysOnInstrumentText")
    post = re.sub(r"^aLeft, aRight\s+blueMixerIn", "aLeft = gaLeft\naRight = gaRight\ngaLeft = 0\ngaRight = 0", post)
    post = post.replace("blueMixerOut a1, a2", "out(a1, a2)")
    rows = []
    with tempfile.TemporaryDirectory(prefix="juno60-voice-") as temporary:
        directory = Path(temporary)
        env = dict(os.environ, CS_USER_PLUGINDIR=temporary,
                   OPCODE7DIR=temporary, OPCODE7DIR64=temporary)

        def render(name, settings, notes=(60,), source_instrument=None):
            source_definitions = definitions
            source_voice, source_post = voice, post
            if source_instrument is not None:
                source_definitions = []
                for udo in source_instrument.findall('opcodeList/udo'):
                    outputs = udo.findtext('outTypes').replace(',', '').replace(' ', '')
                    outputs = '('+','.join(outputs)+')' if len(outputs)>1 else outputs
                    source_definitions.append(f"opcode {udo.findtext('opcodeName')}({udo.findtext('inputArguments')}):{outputs}\n"+udo.findtext('codeBody')+'\nendop\n')
                source_voice = source_instrument.findtext('instrumentText').replace(
                    'blueMixerOut asig, asig', 'gaLeft += asig\ngaRight += asig')
                source_post = re.sub(r'^aLeft, aRight\s+blueMixerIn',
                    'aLeft = gaLeft\naRight = gaRight\ngaLeft = 0\ngaRight = 0',
                    source_instrument.findtext('alwaysOnInstrumentText')).replace('blueMixerOut a1, a2', 'out(a1, a2)')
            text = source_voice + "\nendin\ninstr Output\n" + source_post
            text = text.replace("<INSTR_ID>", "6")
            for key, value in settings.items():
                text = text.replace(f"<{key}>", str(value))
            assert not re.findall(r"<[A-Za-z_]\w*>", text)
            score = '\n'.join(f'i "Voice" 0 2 {note} 0' for note in notes)
            source, wav = directory/"probe.csd", directory/"probe.wav"
            source.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0 --sample-accurate
</CsOptions>
<CsInstruments>
sr = 48000
ksmps = 32
nchnls = 2
0dbfs = 1
seed 1234
gaLeft init 0
gaRight init 0
{''.join(source_definitions)}
instr Voice
{text}
endin
</CsInstruments>
<CsScore>
i "Output" 0 3
{score}
e
</CsScore>
</CsoundSynthesizer>
''')
            result = subprocess.run(["csound", f"--opcode-lib={PLUGIN}",
                                     "-W", "--format=double", "-o", str(wav), str(source)],
                                    env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            left, right, rate = read_stereo(wav)
            assert rate == 48000
            peak = max(max(abs(x) for x in left), max(abs(x) for x in right))
            assert peak < 20, (name, peak)
            # Held-note window excludes attack, release, and converter startup.
            held = left[int(1.5*rate):int(2*rate)]
            row = dict(name=name, chorus=settings["chorus_mode"], voices=len(notes),
                       peak=peak, held_pp=max(held)-min(held),
                       held_abs_median=statistics.median(abs(x) for x in held),
                       held_rms=math.sqrt(sum(x*x for x in held)/len(held)))
            rows.append(row)
            return row

        reference = dict(presets[0][1])
        reference.update(dco_saw_enabled=0, dco_pulse_enabled=1, dco_sub_enabled=0,
                         dco_noise_enabled=0, dco_pwm=0, dco_pwm_source=1,
                         dco_lfo=0, vcf_res=0, vcf_freq=10, vcf_env=0, vcf_lfo=0,
                         vcf_kybd=0, env_attack=0, env_decay=0, env_sustain=10,
                         env_release=0, vca_mode=0, vca_level_adjust=5,
                         hpf_mode=0, chorus_mode=0)
        pulse = render("pulse_reference", reference)
        oscillation = dict(reference, dco_pulse_enabled=0, vcf_res=10, vcf_freq=3)
        ring = render("self_oscillation_reference", oscillation)
        # An open ultrasonic cutoff passes vco2/SRC's band-limited edge
        # overshoot. Compare pulse plateau to sine peak, not the edge extrema.
        assert abs(20*math.log10(2*pulse["held_abs_median"]/ring["held_pp"])) < .5, (pulse,ring)
        assert math.isclose(pulse["held_rms"]/ring["held_rms"], math.sqrt(2), rel_tol=.015), (pulse,ring)
        for mode, cutoff in enumerate((234.61384554, 516.15046019, 1098.19246849), 1):
            filtered = render(f"self_oscillation_hpf_{mode}", dict(oscillation, hpf_mode=mode))
            frequency = 7.8*2**((3/10)*16.6667)
            expected = frequency/math.hypot(frequency, cutoff)
            assert math.isclose(filtered["held_rms"]/ring["held_rms"], expected, rel_tol=.01)
        quiet = render("patch_level_minus5", dict(oscillation, vca_level_adjust=-5))
        assert math.isclose(quiet["held_rms"]/ring["held_rms"], 10**(-24/20), rel_tol=.001)
        for source in ("sub", "noise"):
            values = dict(reference, dco_pulse_enabled=0, **{f"dco_{source}_enabled": 1,
                                                           f"dco_{source}": 10})
            full = render(f"{source}_10", values)
            low = render(f"{source}_2", dict(values, **{f"dco_{source}": 2}))
            zero = render(f"{source}_0", dict(values, **{f"dco_{source}": 0}))
            expected = .2/(1+(50000/47000)*.2*.8)
            assert math.isclose(low["held_rms"]/full["held_rms"], expected, rel_tol=.001)
            assert zero["peak"] == 0
        for mode in (1, 2, 3, 4):
            render(f"chorus_{mode}", dict(reference, chorus_mode=mode))
        render("six_voice_chord", dict(reference, chorus_mode=1), (48, 55, 60, 64, 67, 72))
        print("PASS: full voice calibration, common HPF, patch LEVEL, source controls and chorus modes", flush=True)
        for name, values in presets:
            measured = render(name, values)
            assert measured["peak"] > 1e-5, (name, measured)
            print(f"PASS: full stereo output {name}", flush=True)
        custom_count = 0
        if args.all_presets:
            for assignment in assignments:
                source_instrument = assignment.find('instrument')
                dropdowns = {w.findtext('objectName'):{'id:'+item.get('uniqueId'):str(n)
                    for n,item in enumerate(w.findall('bsbDropdownItemList/bsbDropdownItem'))}
                    for w in source_instrument.findall('.//bsbObject')}
                for preset in source_instrument.find('presetGroup').findall('preset'):
                    settings = {}
                    for entry in preset.findall('setting'):
                        key,value = entry.get('name'),entry.text
                        settings[key] = dropdowns[key][value] if value.startswith('id:') else {'true':'1','false':'0'}.get(value,value)
                    name = f"synth {assignment.get('arrangementId')} / {preset.get('name')}"
                    measured = render(name, settings, source_instrument=source_instrument)
                    assert measured['peak']>1e-5,(name,measured)
                    custom_count += 1
                    print(f'PASS: full stereo output {name}',flush=True)
    output = args.csv
    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = dict(sample_rate=48000, ksmps=32, hold_seconds=2,
                    analysis_window_seconds=[1.5, 2], seed=1234,
                    plugin_sha256=hashlib.sha256((PLUGIN).read_bytes()).hexdigest(),
                    blue_sha256=hashlib.sha256((PROJECT / "fixtures/voice.blue").read_bytes()).hexdigest(),
                    probes=len(rows), factory_presets=len(presets), custom_presets=custom_count,
                    oversampling=4, warm_start=1)
    output.with_suffix(".json").write_text(json.dumps(metadata, indent=2)+"\n")
    print(f"All full-voice checks passed; results in {output}")


if __name__ == "__main__":
    main()
