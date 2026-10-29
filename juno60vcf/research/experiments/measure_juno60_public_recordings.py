#!/usr/bin/env python3
"""Inspect verified public MP3 candidates; do not infer an ENV calibration.

python3 experiments/measure_juno60_public_recordings.py captures/public
Requires the existing ffmpeg, NumPy and SciPy installations. MP3s stay outside
the repository; URLs and hashes come from juno60_public_recordings.json.
"""
from research_paths import PLUGIN, RESULTS
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.io import wavfile
from scipy.signal import find_peaks, stft

from analyze_juno60_control_capture import track_frequency
from check_juno60_startup import ORCHESTRA, render

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio_directory', type=Path)
    args = parser.parse_args()
    manifest = json.loads((PROJECT/'experiments/juno60_public_recordings.json').read_text())
    destination = RESULTS / 'juno60_public_measurements'
    destination.mkdir(parents=True, exist_ok=True)
    rows, spectra = [], []
    with tempfile.TemporaryDirectory(prefix='juno-public-') as temporary:
        for item in manifest['captures']:
            source = args.audio_directory/item['file']
            assert hashlib.sha256(source.read_bytes()).hexdigest() == item['sha256'], source
            wav = Path(temporary)/'decoded.wav'
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),
                            '-c:a','pcm_f32le',str(wav)], check=True)
            rate, audio = wavfile.read(wav)
            assert rate == int(item['sample_rate']) and audio.shape[1] == item['channels']
            rows.append(dict(file=item['file'], source_sha256=item['sha256'], rate=rate,
                decoded_seconds=len(audio)/rate, stereo_correlation=float(np.corrcoef(audio.T)[0,1])))
            # Dominant spectral peaks indicate overlapping voices/harmonics;
            # this is an inspection aid, not an automatic source classifier.
            frequencies, times, spectrum = stft(audio[:,0], rate, nperseg=2048, noverlap=1792)
            magnitude = abs(spectrum)
            for time in (.1,.2,.4,.8,1.2,2,4):
                index = np.argmin(abs(times-time))
                column = magnitude[:,index]
                if column.max() < .015*magnitude.max():
                    continue
                peaks = find_peaks(column, prominence=.1*column.max())[0]
                peaks = peaks[np.argsort(column[peaks])[-6:][::-1]]
                for rank, peak in enumerate(peaks, 1):
                    spectra.append(dict(file=item['file'], time_seconds=float(times[index]),
                        peak_rank=rank, frequency_hz=float(frequencies[peak]),
                        relative_db=float(20*np.log10(column[peak]/column.max()))))
            if item['file'] == 'synthmania-78-Synthesizer-Drum.mp3':
                # Only the first clean portion: later notes overlap. Window
                # selection is specific to this hashed recording, not general.
                times, pitches = track_frequency(audio[:round(.17*rate),0],rate,50,10000)
                keep = (times >= .06) & (times <= .16)
                times, pitches = times[keep], pitches[keep]
                assert len(times) > 100
                with (destination/'drum_first_note.csv').open('w',newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['recording_time_seconds','frequency_hz'])
                    writer.writerows(zip(times,pitches))
                bins = []
                for lo in (.06,.08,.10,.12,.14):
                    values = pitches[(times >= lo) & (times < lo+.02)]
                    bins.append(dict(start_seconds=lo,end_seconds=lo+.02,
                        cycles=len(values),median_hz=float(np.median(values)),
                        p10_hz=float(np.quantile(values,.1)),p90_hz=float(np.quantile(values,.9))))
                metadata = dict(source_url=item['source_url'],sha256=item['sha256'],
                    estimator='interpolated rising-crossing periods in first single-tone passage',
                    bins=bins, calibration='No known baseline, exact note-on time or raw ENV capture; no ENV curve/depth fit')
                orchestra = ORCHESTRA.replace(
                    'aFiltered = juno60_filter(aTestInput, aCutoff, aResonance, aDrive, 1, iThermalNoise, iWarmStart)',
                    'aFiltered = juno60vcf(aTestInput, aCutoff, aResonance, aDrive, 1, 4, iWarmStart)')
                _, model, model_rate = render(Path(temporary), orchestra,
                    'i "FactoryPatch" 0 3.5 78 5 0 0 .3 60',rate,32,native=True)
                assert model_rate == rate
                comparison = []
                for label, signal in [('published_hardware',audio[:round(.17*rate),0]),
                                      ('native_factory_example',np.asarray(model[:round(.17*rate)]))]:
                    times, pitches = track_frequency(signal,rate,50,10000)
                    for threshold in (.005,.01,.02):
                        onset = np.flatnonzero(abs(signal) > threshold*np.max(abs(signal)))[0]/rate
                        relative = times-onset
                        start = np.median(pitches[(relative >= .02) & (relative < .04)])
                        end = np.median(pitches[(relative >= .10) & (relative < .12)])
                        comparison.append(dict(source=label,audio_onset_threshold=threshold,
                            estimated_audio_onset_seconds=onset,early_median_hz=float(start),
                            late_median_hz=float(end),fall_octaves=float(np.log2(start/end))))
                metadata.update(comparison=comparison,
                    comparison_windows_after_audio_onset=[[.02,.04],[.10,.12]],
                    comparison_limit='Audio onset is not key-on. Model MIDI note 60 is an assumed reference; constant tuning offsets cancel from octave fall. Different depth and decay timing can explain a mismatch; neither is fitted.',
                    csd_sha256=hashlib.sha256((PROJECT/'fixtures/Juno60Filter.csd').read_bytes()).hexdigest(),
                    plugin_sha256=hashlib.sha256((PLUGIN).read_bytes()).hexdigest())
                (destination/'drum_first_note.json').write_text(json.dumps(metadata,indent=2)+'\n')
                print(json.dumps(comparison))
    for name, data in [('audio_summary.csv',rows),('spectral_peaks.csv',spectra)]:
        with (destination/name).open('w',newline='') as stream:
            writer = csv.DictWriter(stream,data[0].keys())
            writer.writeheader()
            writer.writerows(data)
    print(f'Inspected {len(rows)} verified files; {destination}')


if __name__ == '__main__':
    main()
