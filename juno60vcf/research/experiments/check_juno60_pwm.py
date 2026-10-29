#!/usr/bin/env python3
"""Render instrument 6's PWM/source section and check circuit-derived mappings."""
from research_paths import RESULTS
import csv
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from check_juno60_patches import read_taps

PROJECT = Path(__file__).resolve().parents[1]


def main():
    instrument = ET.parse(PROJECT / 'fixtures/voice.blue').getroot().find(
        ".//instrumentAssignment[@arrangementId='6']/instrument")
    dropdowns = {widget.findtext('objectName'): {
        'id:'+item.get('uniqueId'): str(index) for index, item in enumerate(
            widget.findall('bsbDropdownItemList/bsbDropdownItem'))}
        for widget in instrument.findall('.//bsbObject')}
    presets = {}
    for preset in instrument.findall(".//presetGroup[@name='Factory']/preset"):
        values = {entry.get('name'): entry.text for entry in preset.findall('setting')}
        presets[int(preset.get('name').split()[0])] = {
            key: dropdowns[key][value] if value.startswith('id:') else
            {'true':'1', 'false':'0'}.get(value, value) for key, value in values.items()}
    voice = instrument.findtext('instrumentText').split(';; Common HPF', 1)[0]
    # Source equations independently computed from schematic resistor values (kOhm).
    load = 82 + .470
    manual = (15/39)/(1/39 + 1/15 + 1/load)
    conductance = 1/120 + 1/33 + 1/82 + 1/load
    bias, amplitude = (15/120)/conductance/manual, (10/82)/conductance/manual
    rows = []
    with tempfile.TemporaryDirectory(prefix='juno60-pwm-') as temporary:
        directory = Path(temporary)
        env = dict(os.environ, CS_USER_PLUGINDIR=temporary,
                   OPCODE7DIR=temporary, OPCODE7DIR64=temporary)

        def render(name, settings, source_instrument=None):
            source_voice = voice if source_instrument is None else re.split(
                r';; (?:Common HPF|highpass:)', source_instrument.findtext('instrumentText'))[0]
            code = source_voice.replace('<INSTR_ID>', '6')
            for key, value in settings.items():
                code = code.replace(f'<{key}>', str(value))
            assert not re.findall(r'<[A-Za-z_]\w*>', code)
            source, wav = directory/'probe.csd', directory/'probe.wav'
            source.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0
</CsOptions>
<CsInstruments>
sr=48000
ksmps=32
nchnls=3
0dbfs=1
instr Lfo
kRate = 0.3 * pow(20/0.3, {settings['lfo_rate']} / 10)
kLfo = lfo:k(1, kRate, 1)
chnset(kLfo, "jno60_lfo_6")
endin
instr Voice
{code}
out(upsamp(kPwmWidth), upsamp(kLfoVal), asig)
skipInit:
endin
</CsInstruments>
<CsScore>
i "Lfo" 0 6
i "Voice" 0 6 60 0
e
</CsScore>
</CsoundSynthesizer>
''')
            result = subprocess.run(['csound', '-W', '--format=double', '-o', str(wav), str(source)],
                                    env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            (width, lfo, signal), rate = read_taps(wav)
            p = float(settings['dco_pwm'])/10
            depth = .45*p/(1+(50/47)*p*(1-p)) if source_instrument is None else .45*p
            source_bias,source_amplitude = (bias,amplitude) if source_instrument is None else (0,1)
            mode = int(settings['dco_pwm_source'])
            if mode != 2:
                expected = [.5+depth*(source_bias+source_amplitude*x if mode == 0 else 1) for x in lfo]
                assert max(abs(a-b) for a,b in zip(width,expected)) < 1e-9, name
            else:
                assert min(width) >= .5 and max(width) <= .5+depth+1e-9
            rows.append(dict(name=name, minimum=min(width), maximum=max(width),
                             mean=sum(width)/len(width), source_peak=max(abs(x) for x in signal)))
            return width, signal

        reference = dict(presets[12], dco_saw_enabled=0, dco_pulse_enabled=1,
                         dco_sub_enabled=0, dco_noise_enabled=0, dco_lfo=0,
                         env_attack=0, env_decay=0, env_sustain=10)
        for panel in (0, 5, 10):
            render(f'manual_{panel}', dict(reference, dco_pwm=panel, dco_pwm_source=1))
        for sustain in (0, 10):
            render(f'env_sustain_{sustain}', dict(reference, dco_pwm=10, dco_pwm_source=2,
                                                env_sustain=sustain))
        strings_width, _ = render('Strings 2', presets[12])
        width = strings_width
        assert math.isclose(min(width), .5028281563, abs_tol=1e-4)
        assert math.isclose(max(width), .7290806617, abs_tol=1e-4)
        for patch in (13, 58):
            width, _ = render(f'patch_{patch}_manual_trigger_off', presets[patch])
            assert max(width)-min(width) > .1
        # PWM must not use the delayed/triggered vibrato path, for any patch.
        width2, _ = render('Strings 2 with vibrato blocked', dict(presets[12],
                          lfo_delay_time=10, lfo_trigger_mode=1, lfo_trig=0))
        assert strings_width == width2
        for number in range(1,6):
            other = ET.parse(PROJECT/'fixtures/voice.blue').getroot().find(
                f".//instrumentAssignment[@arrangementId='{number}']/instrument")
            # Each older synth uses its own raw channel; the probe publishes
            # on 6, so adjust just that channel in this isolated copy.
            entry = other.find('instrumentText')
            entry.text = entry.text.replace(f'"jno60_lfo_{number}"','"jno60_lfo_6"')
            width,_ = render(f'synth_{number}_raw_pwm_manual_trigger_off',dict(reference,
                dco_pwm=6,dco_pwm_source=0,lfo_trigger_mode=1,lfo_trig=0),other)
            assert max(width)-min(width)>.5
        # Verify relative saw/pulse phase in the actual source sum, away from
        # band-limited discontinuities. Common output inversion is immaterial.
        frequency = 440 * 2**((60-69)/12)
        for panel in (0, 6):
            widths, signal = render(f'saw_plus_pulse_phase_{panel}', dict(reference,
                         dco_saw_enabled=1, dco_pwm=panel, dco_pwm_source=1))
            width = widths[-1]
            errors = []
            for index, sample in enumerate(signal[:48000]):
                phase = (index*frequency/48000) % 1
                if min(phase, abs(phase-(1-width)), 1-phase) > .04:
                    pulse = -2*width if phase < 1-width else 2*(1-width)
                    expected = (1-2*phase) + pulse
                    errors.append((sample-expected)**2)
            assert math.sqrt(sum(errors)/len(errors)) < .02
    output = RESULTS/'juno60_pwm.csv'
    with output.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f'PASS: manual/ENV/LFO mappings, free-running PWM and saw/pulse phase; {output}')


if __name__ == '__main__':
    main()
