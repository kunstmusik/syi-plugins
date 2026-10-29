#!/usr/bin/env python3
"""Measure raw ENV through hardware PWM, then render the Blue Attack change.

python3 experiments/measure_juno60_attack_curve.py captures/harman
Capture URLs/hashes are in juno60_attack_curve/captures.json. No emulator
implementation is used. Requires existing NumPy/SciPy and Csound installations.
"""
from research_paths import PLUGIN, RESULTS
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from scipy.io import wavfile
from scipy.optimize import least_squares
from scipy.signal import find_peaks

from check_juno60_startup import render

PROJECT = Path(__file__).resolve().parents[1]
DEST = RESULTS / 'juno60_attack_curve'


def pulse_duty(audio, rate):
    """Interpolated half-plateau crossings; fixed falling edge defines a cycle."""
    edges = find_peaks(-np.diff(audio), distance=round(rate/440*.7),
                       prominence=.025)[0]
    times, duties = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        if a < 3 or not .8*rate/440 < b-a < 1.2*rate/440:
            continue
        cycle = audio[a:b]
        threshold = (cycle.min()+cycle.max())/2
        for _ in range(3):
            threshold = (np.median(cycle[cycle < threshold])+
                         np.median(cycle[cycle > threshold]))/2
        rises = np.flatnonzero((cycle[:-1] < threshold) & (cycle[1:] >= threshold))
        segment = audio[a-3:a+4]
        falls = np.flatnonzero((segment[:-1] > threshold) & (segment[1:] <= threshold))
        if len(rises) != 1 or len(falls) != 1:
            continue
        i, j = rises[0], falls[0]
        rise = i+(threshold-cycle[i])/(cycle[i+1]-cycle[i])
        fall = a-3+j+(threshold-segment[j])/(segment[j+1]-segment[j])
        times.append((a+b)/2/rate)
        duties.append((b-a-rise+fall-a)/(b-a))
    return np.asarray(times), np.asarray(duties)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio_directory', type=Path)
    args = parser.parse_args()
    manifest = json.loads((PROJECT/'experiments/juno60_attack_curve/captures.json').read_text())
    rows, traces = [], []
    for name in ('Juno 60 PWM=5.wav', 'Juno 60 PWM=10.wav', 'Juno 60 PWM10Sus=0.wav'):
        entry = next(x for x in manifest['captures'] if x['file'] == name)
        path = args.audio_directory/name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']
        rate, raw = wavfile.read(path)
        assert raw.dtype == np.int32 and raw.shape[1] == 2 and rate == 44100
        times, duty = pulse_duty(raw[:,0].astype(float)/2**31, rate)
        # Attack plus the first .8s of decay constrains the turning point.
        # D, sustain, gain/offset and start time are nuisance parameters, not
        # proposed production calibrations. Panel positions were set manually.
        start, peak = times[0], times[np.argmax(duty)]
        keep = times < peak+.8

        def model(v):
            t0, duration, curve, decay, dcurve, lo, hi, sustain = v
            t = times[keep]-t0
            attack = np.expm1(curve*np.clip(t/duration, 0, 1))/np.expm1(curve)
            falling = 1-np.expm1(dcurve*np.clip((t-duration)/decay, 0, 1))/np.expm1(dcurve)
            return lo+(hi-lo)*np.where(t < duration, attack, sustain+(1-sustain)*falling)

        initial = [start-.003, peak-start, -1, 1, -4, .5, max(duty),
                   0 if 'Sus=0' in name else .5]
        bounds = ([start-.05,.1,-5,.5,-7,.46,.6,0],
                  [start+.01,.4,-.05,2,-1,.55,.98,.7])
        fit = least_squares(lambda v: model(v)-duty[keep], initial, bounds=bounds)
        assert fit.success
        measured = times[keep]-fit.x[0]
        attack_only = (measured >= .02) & (measured < fit.x[1]-.01)
        row = dict(file=name, attack_seconds=float(fit.x[1]),
                   fitted_attack_curve=float(fit.x[2]),
                   fit_duty_rmse=float(np.sqrt(np.mean(fit.fun**2))))
        for label, curve in [('previous',-4.2),('corrected',-1)]:
            candidate = fit.x.copy()
            candidate[2] = curve
            row[label+'_attack_rmse'] = float(np.sqrt(np.mean(
                ((model(candidate)-duty[keep])[attack_only]/(fit.x[6]-fit.x[5]))**2)))
        assert -1.3 < fit.x[2] < -.7, row
        assert row['corrected_attack_rmse'] < row['previous_attack_rmse']/8, row
        rows.append(row)
        for t, d in zip(measured[attack_only], duty[keep][attack_only]):
            traces.append(dict(file=name, normalized_attack_time=float(t/fit.x[1]),
                               normalized_duty=float((d-fit.x[5])/(fit.x[6]-fit.x[5]))))
    for filename, data in [('measurements.csv', rows), ('attack_traces.csv', traces)]:
        with (DEST/filename).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, data[0].keys())
            writer.writeheader()
            writer.writerows(data)

    # Keep the fast VCA observation separate: cycle amplitude is not raw ENV.
    name = 'Juno 60 Attk=0.wav'
    path = args.audio_directory/name
    entry = next(x for x in manifest['captures'] if x['file'] == name)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']
    rate, raw = wavfile.read(path)
    audio = raw[:,0].astype(float)/2**31
    edges = find_peaks(-np.diff(audio), distance=round(rate/440*.7), prominence=.002)[0]
    cycles = []
    for a, b in zip(edges[:-1], edges[1:]):
        if .9*rate/440 < b-a < 1.1*rate/440:
            cycle = audio[a:b]
            cycles.append(((a+b)/2/rate, np.quantile(cycle,.8)-np.quantile(cycle,.2)))
    cycles = np.asarray(cycles)
    onset = np.flatnonzero(abs(audio) > .001)[0]/rate
    peak = np.max(cycles[:,1])
    selected = cycles[(cycles[:,0] >= onset) & (cycles[:,0] < onset+.025)]
    (DEST/'minimum_attack_observation.json').write_text(json.dumps(dict(
        file=name, estimated_audio_onset_seconds=onset, threshold=.001,
        estimator='80th minus 20th percentile in complete falling-edge cycles',
        samples=[dict(ms_after_audio_onset=float(1000*(t-onset)),
                      normalized_cycle_pp=float(g/peak)) for t,g in selected],
        limitation='Audio amplitude includes VCA and recording path, not raw ENV. Key-on unavailable; no new RC fit is asserted.'),
        indent=2)+'\n')

    root = ET.parse(PROJECT/'fixtures/voice.blue').getroot()
    instrument = root.find(".//instrumentAssignment[@arrangementId='6']/instrument")
    before = json.loads((PROJECT/'fixtures/attack_baseline.json').read_text())
    voice = instrument.findtext('instrumentText')
    # Ensure the A/B isolates exactly one change, including its explanatory comment.
    expected = before['voice'].replace(
        'aEnv = transegr:a(0, iEnvA, -4.2,',
        '; Raw ENV Attack: -1 curve supported by hardware PWM captures; D/R provisional.\n'
        'aEnv = transegr:a(0, iEnvA, -1,')
    assert voice == expected
    definitions = []
    for udo in instrument.findall('opcodeList/udo'):
        outputs = udo.findtext('outTypes').replace(',', '').replace(' ', '')
        outputs = '('+','.join(outputs)+')' if len(outputs) > 1 else outputs
        definitions.append(f"opcode {udo.findtext('opcodeName')}({udo.findtext('inputArguments')}):{outputs}\n"
                           +udo.findtext('codeBody')+'\nendop\n')
    post = instrument.findtext('alwaysOnInstrumentText')
    # Match the existing full-voice probe's whitespace-tolerant mixer replacement.
    post = re.sub(r'^aLeft, aRight\s+blueMixerIn',
                  'aLeft = gaLeft\naRight = gaRight\ngaLeft = 0\ngaRight = 0', post)
    post = post.replace('blueMixerOut a1, a2', 'out(a1, a2)')
    audio_order, metrics = [], []
    with tempfile.TemporaryDirectory(prefix='juno60-attack-') as temporary:
        directory = Path(temporary)
        for chorus in (0, 1):
            audition = []
            for number in ('14','15','16'):
                settings = dict(before['organs'][number], chorus_mode=chorus)
                for label, body in [('before',before['voice']),('after',voice)]:
                    body = body.replace('blueMixerOut asig, asig', 'gaLeft += asig\ngaRight += asig')
                    orchestra = 'sr = 48000\nksmps = 32\nnchnls = 2\n0dbfs = 1\ngaLeft init 0\ngaRight init 0\n'
                    orchestra += ''.join(definitions)+'\ninstr Voice\n'+body+'\nendin\ninstr Output\n'+post+'\nendin\n'
                    orchestra = orchestra.replace('<INSTR_ID>', '6')
                    for key, value in settings.items():
                        orchestra = orchestra.replace(f'<{key}>', str(value))
                    assert not re.findall(r'<[A-Za-z_]\w*>', orchestra)
                    left, right, rate = render(directory, orchestra,
                        'i "Output" 0 .8\ni "Voice" 0 .3 60 0', 48000, 32, native=True)
                    stereo = np.column_stack((left,right))
                    assert np.isfinite(stereo).all() and abs(stereo).max() < 4
                    # Common gain only; preserve before/after level differences.
                    audition.extend(stereo[:24000]*.25)
                    audition.extend(np.zeros((14400,2)))
                    metrics.append(dict(patch=number, chorus=chorus, variant=label,
                        first10ms_rms=float(np.sqrt(np.mean(stereo[:480]**2))),
                        first50ms_rms=float(np.sqrt(np.mean(stereo[:2400]**2))),
                        held_rms=float(np.sqrt(np.mean(stereo[9600:14400]**2)))))
                    if chorus == 0:
                        audio_order.append(f'Organ {int(number)-13} {label}')
            samples = np.asarray(audition)
            assert abs(samples).max() < 1
            # Existing SciPy WAV writer gives a portable floating-point stereo WAV.
            wavfile.write(DEST/f'organ_attack_{"dry" if chorus == 0 else "chorus"}.wav',
                          48000, samples.astype(np.float32))
    with (DEST/'organ_metrics.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, metrics[0].keys())
        writer.writeheader()
        writer.writerows(metrics)
    (DEST/'results.json').write_text(json.dumps(dict(
        source=manifest['source'], fits=rows, waveform='raw ENV recovered through PWM duty, independently of audio amplitude',
        method='half-plateau crossings; bounded least squares; no imported emulator code',
        limitation='One hardware unit; approximate panel positions; gain, switching, filter and recorder response not fully separated',
        production_change='Attack curve -4.2 to -1 only; ADR timing, D/R shape and Gate unchanged',
        audition_order=audio_order, common_gain=.25, slot_seconds=.8, midi_note=60,
        output_stage='actual instrument 6 common HPF/LEVEL; chorus off or factory mode 1',
        blue_sha256=hashlib.sha256((PROJECT/'fixtures/voice.blue').read_bytes()).hexdigest(),
        plugin_sha256=hashlib.sha256((PLUGIN).read_bytes()).hexdigest()),
        indent=2)+'\n')
    print(json.dumps(rows, indent=2))
    print(f'PASS: measured Attack curve and isolated stereo Organ A/B; {DEST}')


if __name__ == '__main__':
    main()
