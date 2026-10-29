#!/usr/bin/env python3
"""Measure isolated Andy Harman LFO WAVs (download URLs/hashes in juno60_lfo/captures.json).

python3 experiments/measure_juno60_lfo.py captures/harman
Requires existing NumPy/SciPy. Source WAVs are not redistributed. Rate 0 is too
short for a period estimate; file labels are approximate physical slider settings.
"""
from research_paths import RESULTS
import argparse
import csv
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np
from scipy.io import wavfile
from scipy.optimize import least_squares
from scipy.signal import butter, find_peaks, hilbert, savgol_filter, sosfiltfilt

from analyze_juno60_control_capture import track_frequency

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures', type=Path)
    parser.add_argument('--output', type=Path, default=RESULTS / 'juno60_lfo')
    args = parser.parse_args()
    manifest = json.loads((PROJECT/'experiments/juno60_lfo/captures.json').read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    rows, shape = [], {}
    for entry in manifest['files']:
        if not entry['path'].endswith('.wav'):
            continue
        path = args.captures/entry['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], path
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', wavfile.WavFileWarning)
            sr, audio = wavfile.read(path)
        audio = audio.astype(float)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)  # documented identical/dry test outputs
        amplitude = np.sqrt(np.convolve(audio*audio, np.ones(441)/441, 'same'))
        held = np.flatnonzero(amplitude > amplitude.max()*.2)
        onset, offset = held[0]/sr, held[-1]/sr
        times = np.arange(len(audio))/sr
        # Independent fundamental-phase estimator for period, unaffected by
        # rising-crossing jitter from the recorded pulse-wave edge.
        band = sosfiltfilt(butter(3, [285,590], fs=sr, btype='bandpass', output='sos'), audio)
        phase = np.unwrap(np.angle(hilbert(band)))
        frequency = savgol_filter(np.gradient(phase)*sr/(2*np.pi),441,3)
        peaks, _ = find_peaks(frequency, prominence=10, distance=sr*.03)
        peaks = peaks[(times[peaks] > onset+.1) & (times[peaks] < offset-.1)]
        hz = float(1/np.polyfit(np.arange(len(peaks)), times[peaks], 1)[0]) if len(peaks)>1 else None
        # Depth/onset use the existing independent period-between-crossings
        # estimator. Exclude note attack/release, where phase estimates spike.
        t, f = track_frequency(audio, sr, 300, 600)
        valid = (t>onset+.03)&(t<offset-.03)
        t, f = t[valid], f[valid]
        cents = savgol_filter(1200*np.log2(f),11,2)
        high, _ = find_peaks(cents, prominence=25, distance=5)
        low, _ = find_peaks(-cents, prominence=25, distance=5)
        upper = float(np.median(cents[high][-15:])) if len(high) else None
        lower = float(np.median(cents[low][-15:])) if len(low) else None
        depth = (upper-lower)/2 if upper is not None and lower is not None else None
        row = dict(file=entry['path'],onset_seconds=onset,offset_seconds=offset,
                   rate_hz=hz,half_range_cents=depth,delay_seconds=None,fade_seconds=None,fade_rmse=None)
        if '/Delay/' in entry['path']:
            base = np.median(cents[t < onset+(.04 if '2.5' in path.name else .2)])
            gains = np.r_[(cents[high]-base)/(upper-base),(base-cents[low])/(base-lower)]
            gain_times = np.r_[t[high]-onset,t[low]-onset]
            def residual(parameters):
                return np.clip((gain_times-parameters[0])/parameters[1],0,1)-gains
            fit = least_squares(residual,[max(0,gain_times[0]-.04),.4],bounds=([0,.01],[3.5,2]))
            row.update(delay_seconds=float(fit.x[0]),fade_seconds=float(fit.x[1]),
                       fade_rmse=float(np.sqrt(np.mean(residual(fit.x)**2))))
        if 'DCOmod 10' in path.name:
            # Fit phase and rounded-triangle curvature in the cents domain;
            # this includes the physical clock converter's small asymmetry.
            period = np.median(np.diff(t[high]))
            normalized = (cents-(upper+lower)/2)/depth
            for kind in ('sine','triangle','tanh'):
                def wave_residual(parameters):
                    angle = 2*np.pi*(t-parameters[0])/period
                    triangle = 2/np.pi*np.arcsin(np.sin(angle))
                    wave = np.sin(angle) if kind=='sine' else triangle if kind=='triangle' else np.tanh(parameters[1]*triangle)/np.tanh(parameters[1])
                    return wave-normalized
                fit = least_squares(wave_residual,[0,1.5],bounds=([-2,.1],[2,5]))
                shape[kind] = dict(curvature=float(fit.x[1]) if kind=='tanh' else None,
                    normalized_rmse=float(np.sqrt(np.mean(wave_residual(fit.x)**2))))
            with (args.output/'pitch_shape.csv').open('w',newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['seconds_from_note_onset','normalized_pitch_modulation'])
                writer.writerows(zip((t-onset)[::4],normalized[::4]))
        rows.append(row)
        print(path.name, 'Hz', None if hz is None else round(hz,4),
              'cents', None if depth is None else round(depth,2),
              'hold/fade', row['delay_seconds'],row['fade_seconds'])
    with (args.output/'measurements.csv').open('w',newline='') as stream:
        writer = csv.DictWriter(stream,rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    metadata = dict(source_commit=manifest['commit'],measurement='dry pulse frequency; two independent estimators',
        limitations=['Physical panel positions and calibration are approximate.',
            'Rate 0 has no complete cycle; nominal 0.3Hz retained.',
            'No isolated DCO depth below 5 or MANUAL delay capture.',
            'Depth is half peak-to-peak cents, centered; converter asymmetry is not reproduced.',
            'Delay fit subtracts note onset; README timing differs in several rows.'],
        shape=shape,measurements=rows)
    (args.output/'results.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print('Waveform fits:',shape)


if __name__=='__main__':
    main()
