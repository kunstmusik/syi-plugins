#!/usr/bin/env python3
"""Recover octave movement from an isolated, chorus-free self-oscillation WAV.

Example: python3 experiments/analyze_juno60_control_capture.py take.wav \
    --base-hz 248 --depth-octaves 4 --channel 1 --start .1 --end 1.5

Use measured baseline and depth. Input is not assumed to be original hardware.
Requires the existing NumPy/SciPy environment; supports PCM and float WAV.
"""
from research_paths import RESULTS
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile


def dominant_frequency(signal, rate, minimum=80, maximum=40000):
    """Windowed spectral peak for a held tone, including ultrasonic calibration."""
    signal = np.asarray(signal, dtype=float)
    if len(signal) < 32 or not np.all(np.isfinite(signal)) or not np.max(np.abs(signal)) > 0:
        raise ValueError('Selected interval must contain finite, nonzero audio')
    spectrum = np.abs(np.fft.rfft(signal*np.hanning(len(signal))))
    low = max(1, int(np.ceil(minimum*len(signal)/rate)))
    high = min(len(spectrum)-1, int(maximum*len(signal)/rate)+1)
    if high <= low:
        raise ValueError('Invalid spectral frequency range')
    peak = np.argmax(spectrum[low:high])+low
    left, center, right = np.log(np.maximum(spectrum[peak-1:peak+2], np.finfo(float).tiny))
    denominator = left-2*center+right
    offset = .5*(left-right)/denominator if denominator else 0
    return float((peak+np.clip(offset,-.5,.5))*rate/len(signal))


def track_frequency(signal, rate, minimum=80, maximum=10000):
    """Estimate period between rising zero crossings, timestamped at midpoint.

    Intended for a clean single oscillator. Chorus, DCO mixtures, noise and
    near-Nyquist signals are unsuitable; an estimate is not a source classifier.
    """
    signal = np.asarray(signal, dtype=float)
    if not np.all(np.isfinite(signal)) or not np.max(np.abs(signal)) > 0:
        raise ValueError('Recording must contain finite, nonzero audio')
    indices = np.flatnonzero((signal[:-1] <= 0) & (signal[1:] > 0))
    if len(indices) < 3:
        raise ValueError('Too few rising zero crossings')
    crossings = indices - signal[indices]/(signal[indices+1]-signal[indices])
    frequency = rate/np.diff(crossings)
    times = (crossings[:-1]+crossings[1:])/(2*rate)
    # Reject silence and very quiet tails, where noise crossings dominate.
    peaks = np.array([np.max(np.abs(signal[a:b+1]))
                      for a, b in zip(indices[:-1], indices[1:])])
    valid = (frequency >= minimum) & (frequency <= maximum)
    valid &= peaks >= .01*np.max(np.abs(signal))
    if np.count_nonzero(valid) < 3:
        raise ValueError('Too few usable cycles in the selected frequency range')
    return times[valid], frequency[valid]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--base-hz', type=float, required=True)
    parser.add_argument('--depth-octaves', type=float,
                        help='Measured signed peak depth; omit for static depth tests')
    parser.add_argument('--channel', type=int, default=1, help='One-based WAV channel')
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--end', type=float)
    parser.add_argument('--min-hz', type=float, default=80)
    parser.add_argument('--max-hz', type=float, default=10000)
    parser.add_argument('--static', action='store_true',
                        help='Measure one held-tone spectral peak over the selected interval')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not np.isfinite(args.base_hz) or args.base_hz <= 0 or args.depth_octaves == 0:
        parser.error('Baseline must be positive and depth must be nonzero')
    if args.depth_octaves is not None and not np.isfinite(args.depth_octaves):
        parser.error('Depth must be finite')
    if not np.isfinite(args.start) or args.start < 0 or (args.end is not None and
            (not np.isfinite(args.end) or args.end <= args.start)):
        parser.error('Time interval must be positive and ordered')
    rate, audio = wavfile.read(args.recording)
    if not 0 < args.min_hz < args.max_hz < rate/2:
        parser.error('Frequency range must be positive, ordered and below recording Nyquist')
    channels = 1 if audio.ndim == 1 else audio.shape[1]
    if not 1 <= args.channel <= channels:
        parser.error(f'Recording has {channels} channel(s)')
    signal = audio if channels == 1 else audio[:, args.channel-1]
    if args.static:
        start, end = int(args.start*rate), int(args.end*rate) if args.end else len(signal)
        end = min(end,len(signal))
        frequency = np.array([dominant_frequency(signal[start:end],rate,args.min_hz,args.max_hz)])
        times = np.array([(start+end)/(2*rate)])
    else:
        times, frequency = track_frequency(signal, rate, args.min_hz, args.max_hz)
        valid = times >= args.start
        if args.end is not None:
            valid &= times <= args.end
        times, frequency = times[valid], frequency[valid]
        if len(times) < 3:
            parser.error('Selected time interval contains too few usable cycles')
    octaves = np.log2(frequency/args.base_hz)
    columns = ['time_seconds', 'frequency_hz', 'octaves_from_base']
    values = [times, frequency, octaves]
    if args.depth_octaves is not None:
        columns.append('estimated_envelope')
        values.append(octaves/args.depth_octaves)
    output = args.output or (RESULTS / args.recording.with_suffix('.control.csv').name)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='') as target:
        writer = csv.writer(target)
        writer.writerow(columns)
        writer.writerows(zip(*values))
    metadata = dict(recording=args.recording.name,
        sha256=hashlib.sha256(args.recording.read_bytes()).hexdigest(), rate=rate,
        channel=args.channel, baseline_hz=args.base_hz, depth_octaves=args.depth_octaves,
        start=args.start, end=args.end,
        estimator='windowed FFT peak' if args.static else 'rising-crossing period at midpoint',
        provenance='User-supplied audio; hardware origin is not verified',
        estimates=len(times), median_hz=float(np.median(frequency)),
        median_octaves=float(np.median(octaves)))
    output.with_suffix('.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(f'{len(times)} estimates; median {metadata["median_hz"]:.6f} Hz; '
          f'{metadata["median_octaves"]:.6f} octaves from base; {output}')


if __name__ == '__main__':
    main()
