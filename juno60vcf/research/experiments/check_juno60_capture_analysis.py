#!/usr/bin/env python3
"""Validate pitch-to-envelope recovery against actual native filter renders."""
from research_paths import PLUGIN, RESULTS
import csv
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

import numpy as np
from scipy.optimize import minimize_scalar

from analyze_juno60_control_capture import dominant_frequency, track_frequency
from check_juno60_patches import PROJECT, read_taps


def main():
    for hz in (247.8,31948.807):
        rate = 96000
        sine = .5*np.sin(2*np.pi*hz*np.arange(rate//2)/rate)
        pcm = np.round(sine*(2**23-1))
        measured = dominant_frequency(pcm,rate)
        assert abs(measured-hz) < .04, (hz,measured)
    print('PASS: spectral estimator covers audible and ultrasonic held tones within 0.04 Hz')
    destination = RESULTS / 'juno60_control_mapping'
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix='juno60-capture-') as temporary:
        directory = Path(temporary)
        environment = dict(os.environ, CS_USER_PLUGINDIR=temporary,
                           OPCODE7DIR=temporary, OPCODE7DIR64=temporary)
        for rate in (48000, 96000):
            for attack in (.25, .001):
                for curve in (0, -4.2):
                    csd, wav = directory/'probe.csd', directory/'probe.wav'
                    csd.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0 --sample-accurate
</CsOptions>
<CsInstruments>
sr={rate}
ksmps=32
nchnls=3
0dbfs=1
instr Probe
aEnv=transegr:a(0,{attack},{curve},1,.5,{curve},.3,.5,{curve},0)
aCutoff=248*exp(log(2)*4*aEnv)
aOsc=juno60vcf(a(0),aCutoff,1,1,1,2)
out(aEnv,aCutoff,aOsc)
endin
</CsInstruments>
<CsScore>
i "Probe" 0 1.5
e
</CsScore>
</CsoundSynthesizer>
''')
                    result = subprocess.run(['csound',
                        f'--opcode-lib={PLUGIN}',
                        '-W', '--format=double', '-o', str(wav), str(csd)],
                        env=environment, capture_output=True, text=True, timeout=30)
                    assert result.returncode == 0, result.stderr
                    (envelope, cutoff, audio), actual_rate = read_taps(wav)
                    assert actual_rate == rate
                    times, frequency = track_frequency(audio, rate)
                    # Align the native medium-sinc latency, then compare to
                    # the actual control tap rather than another ENV model.
                    control_times = times-94/rate
                    recovered = np.log2(frequency/248)/4
                    reference = np.interp(control_times,
                        np.arange(len(envelope))/rate, envelope)
                    valid = (control_times > .02) & (control_times < attack-.02)
                    count = int(np.count_nonzero(valid))
                    if attack == .001:
                        fast = (control_times >= 0) & (control_times <= attack)
                        fast_cycles = int(np.count_nonzero(fast))
                        rmse = float(np.sqrt(np.mean((recovered[fast]-reference[fast])**2))) if fast_cycles else ''
                        rows.append(dict(rate=rate, attack_seconds=attack, curve=curve,
                            fitted_curve='',attack_cycles=fast_cycles,envelope_rmse=rmse))
                        print(f'LIMIT: {rate} Hz, curve {curve:g}, {fast_cycles} cycle estimates in 1 ms attack, RMSE {rmse}')
                        continue
                    error = recovered[valid]-reference[valid]
                    rmse = float(np.sqrt(np.mean(error**2)))
                    assert rmse < .015, (rate, curve, rmse)
                    phase = control_times[valid]/attack
                    def model_error(candidate):
                        predicted = (phase if abs(candidate) < 1e-6 else
                                     np.expm1(candidate*phase)/np.expm1(candidate))
                        return np.mean((predicted-recovered[valid])**2)
                    fitted = float(minimize_scalar(model_error, bounds=(-8, 2),
                                                   method='bounded').x)
                    assert abs(fitted-curve) < .25, (curve, fitted)
                    rows.append(dict(rate=rate, attack_seconds=attack, curve=curve,
                        fitted_curve=fitted, attack_cycles=count, envelope_rmse=rmse))
                    if rate == 96000 and curve == -4.2:
                        with (destination/'recovered_envelope.csv').open('w', newline='') as output:
                            writer = csv.writer(output)
                            writer.writerow(['time_seconds','frequency_hz','estimated_envelope','reference_envelope'])
                            writer.writerows(zip(control_times, frequency, recovered, reference))
                        # Exercise the public CLI on ordinary 24-bit mono audio.
                        pcm = (np.asarray(audio)*.25*(2**23-1)).astype('<i4')
                        raw = pcm.view(np.uint8).reshape(-1,4)[:,:3].tobytes()
                        recording = directory/'capture.wav'
                        with wave.open(str(recording),'wb') as output:
                            output.setparams((1,3,rate,0,'NONE','not compressed'))
                            output.writeframes(raw)
                        result = subprocess.run([sys.executable, str(PROJECT/'experiments/analyze_juno60_control_capture.py'),
                            str(recording),'--base-hz','248','--depth-octaves','4',
                            '--start','.03','--end','.2'], capture_output=True,text=True)
                        assert result.returncode == 0, result.stderr
                        print('PASS: 24-bit mono recording CLI')
                        control_output = directory/'probe.control.csv'
                        result = subprocess.run([sys.executable,str(PROJECT/'experiments/analyze_juno60_control_capture.py'),
                            str(wav),'--channel','3','--static','--base-hz','248',
                            '--depth-octaves','4','--start','1','--end','1.4',
                            '--output',str(control_output)],capture_output=True,text=True)
                        assert result.returncode == 0, result.stderr
                        with control_output.open() as source:
                            static = next(csv.DictReader(source))
                        assert abs(float(static['estimated_envelope'])-.3) < .001, static
                        print('PASS: float multichannel held-tone CLI')
                    print(f'PASS: {rate} Hz, curve {curve:g}, recovered fit {fitted:.5f}, RMSE {rmse:.6f}')
    with (destination/'capture_validation.csv').open('w',newline='') as output:
        writer = csv.DictWriter(output,rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print('LIMIT: the tested 1 ms attacks give sparse cycle estimates; no curvature fit is reported')


if __name__ == '__main__':
    main()
