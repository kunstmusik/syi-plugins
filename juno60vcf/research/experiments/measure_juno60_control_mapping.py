#!/usr/bin/env python3
"""Measure the existing Blue cutoff formula and native oscillation frequency.

Software measurements only; no hardware curve is fitted by this script.
"""
from research_paths import PLUGIN, RESULTS
import csv
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from analyze_juno60_control_capture import dominant_frequency
from check_juno60_patches import PROJECT, read_taps


def main():
    voice = ET.parse(PROJECT/'fixtures/voice.blue').find(
        ".//instrumentAssignment[@arrangementId='6']/instrument/instrumentText").text
    cutoff = re.search(r'^acutoff = (.*?) ;;', voice, re.M).group(1)
    slope = float(re.search(r'^kcut_freq = .*?\* ([\d.]+)', voice, re.M).group(1))
    depth_control = voice.split('; VCF ENV:',1)[1].split('; VCF LFO',1)[0]
    depth_control = '; VCF ENV:'+depth_control
    destination = RESULTS / 'juno60_control_mapping'
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    cases = [(rate, factor, 3, 0, 0) for rate in (48000, 96000) for factor in (2,)]
    cases += [(rate, factor, 0, 10, 1) for rate in (44100, 48000, 96000) for factor in (1, 2, 4)]
    # Nominal PNP driver: panel 4.06738483 now gives four octaves.
    cases += [(96000, 2, 3, 4.067384830523231, e) for e in (0, .25, .5, .75, 1)]
    with tempfile.TemporaryDirectory(prefix='juno60-cv-') as temporary:
        directory = Path(temporary)
        environment = dict(os.environ, CS_USER_PLUGINDIR=temporary,
                           OPCODE7DIR=temporary, OPCODE7DIR64=temporary)
        for rate, factor, panel_freq, panel_env, envelope in cases:
            csd, wav = directory/'probe.csd', directory/'probe.wav'
            csd.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0
</CsOptions>
<CsInstruments>
sr={rate}
ksmps=32
nchnls=3
0dbfs=1
instr Probe
aEnv={envelope}
{depth_control.replace('<vcf_env>',str(panel_env))}
acut=aEnv*kEnvModOct
kcut={panel_freq/10*slope}
acutoff={cutoff}
aOsc=juno60vcf(a(0),acutoff,1,1,1,{factor})
out(aEnv,acutoff,aOsc)
endin
</CsInstruments>
<CsScore>
i "Probe" 0 2
e
</CsScore>
</CsoundSynthesizer>
''')
            result = subprocess.run(['csound',
                f'--opcode-lib={PLUGIN}',
                '-W', '--format=double', '-o', str(wav), str(csd)],
                env=environment, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            (env, command, oscillation), actual_rate = read_taps(wav)
            assert actual_rate == rate
            tail = oscillation[-rate:]
            level = math.sqrt(sum(x*x for x in tail)/len(tail))
            peak = dominant_frequency(tail,rate,maximum=rate/2) if level > 1e-12 else ''
            requested = command[-1]
            effective = min(requested,.49*rate*factor)
            # Above output Nyquist, a surviving FFT peak is residual/alias
            # energy, not a measurement of the ultrasonic oscillator itself.
            measured = peak if effective < rate/2 else ''
            rows.append(dict(rate=rate, oversampling=factor, freq_panel=panel_freq, env_panel=panel_env,
                envelope=envelope, requested_hz=requested,
                effective_cutoff_hz=effective, oscillator_hz=measured,
                error_cents=1200*math.log2(measured/effective) if measured else '',
                output_dominant_hz=peak, output_rms=level,
                output_rms_dbfs=20*math.log10(level) if level else '',
                observation='in-band oscillator' if measured else 'ultrasonic oscillator; output residual only'))
            print(f'{rate}/{factor}x: FREQ={panel_freq:g} ENV={panel_env:g} E={envelope:g}: '
                  f'command {requested:.6f} Hz, oscillator {measured or "out of band"}, RMS {level:.6g}')
    with (destination/'static.csv').open('w', newline='') as output:
        writer = csv.DictWriter(output, rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


if __name__ == '__main__':
    main()
