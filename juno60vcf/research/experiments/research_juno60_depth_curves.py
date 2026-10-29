#!/usr/bin/env python3
"""Analyze hashed hardware captures without changing production mappings.

python3 experiments/research_juno60_depth_curves.py captures/filter captures/harman
Pole estimates assume four equal linear stages and no resonance. Their
agreement is a model check, not proof of recording settings or hardware accuracy.
"""
from research_paths import PLUGIN, RESULTS
import argparse
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import warnings

import numpy as np
from scipy.io import wavfile
from scipy.optimize import least_squares
from scipy.signal import butter, hilbert, savgol_filter, sosfiltfilt

PROJECT = Path(__file__).resolve().parents[1]
DEST = RESULTS / 'juno60_depth_curves'


def read(path):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', wavfile.WavFileWarning)
        sr, audio = wavfile.read(path)
    if audio.dtype.kind == 'i':
        audio = audio.astype(float) / 2**(audio.dtype.itemsize*8-1)
    elif audio.dtype.kind == 'u':
        audio = (audio.astype(float)-128)/128
    else:
        audio = audio.astype(float)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    assert np.isfinite(audio).all()
    return sr, audio


def held(audio, sr, threshold=.15):
    envelope = np.sqrt(np.convolve(audio*audio, np.ones(441)/441, 'same'))
    samples = np.flatnonzero(envelope > envelope.max()*threshold)
    return samples[0]/sr, samples[-1]/sr


def coefficients(audio, phase, ids, orders):
    window = np.hanning(len(ids))
    return np.array([abs(2*np.sum(audio[ids]*window*np.exp(-1j*n*phase[ids])) /
                         window.sum()) for n in orders])


def harmonics(path, base=55, count=180):
    sr, audio = read(path)
    onset, offset = held(audio, sr)
    time = np.arange(len(audio))/sr
    band = sosfiltfilt(butter(3, [base*.7, base*1.3], fs=sr,
                            btype='bandpass', output='sos'), audio)
    phase = np.unwrap(np.angle(hilbert(band)))
    valid = (time > onset+.15) & (time < offset-.15)
    f0 = np.polyfit(time[valid], phase[valid], 1)[0]/(2*np.pi)
    frames = []
    for start in np.arange(onset+.2, offset-.35, .25):
        ids = np.flatnonzero((time >= start) & (time < start+.25))
        frames.append(coefficients(audio, phase, ids, range(1, count+1)))
    return float(f0), np.median(frames, axis=0)


def fit_wave(time, pole):
    """Fit rounded triangle in log2 Hz; sparse phase coverage can be ambiguous."""
    def residual(z):
        triangle = 2/np.pi*np.arcsin(np.sin(2*np.pi*(time*z[4]+z[3])))
        wave = np.tanh(z[2]*triangle)/np.tanh(z[2])
        return z[0]+z[1]*wave-np.log2(pole)
    fits = [least_squares(residual, [np.log2(600), 2, 2, phase, 1.1],
             bounds=([np.log2(5), 0, .05, -2, .7],
                     [np.log2(10000), 8, 5, 2, 1.4]))
            for phase in np.arange(-.5, .5, .2)]
    fit = min(fits, key=lambda x: np.sum(x.fun*x.fun))
    return dict(center_hz=float(2**fit.x[0]), half_range_octaves=float(fit.x[1]),
                shape=float(fit.x[2]), rate_hz=float(fit.x[4]),
                rmse_octaves=float(np.sqrt(np.mean(fit.fun*fit.fun))))


def from_ratio(frequency, ratio, harmonic):
    # sqrt(H_n/H_1) = (1+x)/(1+n^2*x), x=(f/fc)^2.
    q = np.sqrt(ratio)
    with np.errstate(invalid='ignore', divide='ignore'):
        x = (1-q)/(harmonic*harmonic*q-1)
        pole = frequency/np.sqrt(x)
    return pole, q


def self_check():
    # Independent analytic four-pole responses recover a grid of known poles.
    frequency = 440.
    for pole in [100, 250, 600, 1300, 4000]:
        transfer = (1+(frequency*np.array([1, 3, 5])/pole)**2)**-2
        for n, ratio in zip([3, 5], transfer[1:]/transfer[0]):
            recovered, _ = from_ratio(frequency, ratio, n)
            assert abs(recovered/pole-1) < 1e-10


def native_resonance():
    from check_juno60_startup import PLUGIN, render
    rows = []
    with tempfile.TemporaryDirectory(prefix='juno-depth-resonance-') as temporary:
        for amplitude in [.25, 1, 2]:
            for law in ['linear', 'loaded_current']:
                group = []
                for panel in [0, 2.5, 5, 7.5, 10]:
                    p = panel/10
                    loaded = p/(1+(50/47)*p*(1-p))
                    resonance = p if law == 'linear' else max(5*loaded-.57, 0)/4.43
                    orchestra = f'''sr = 48000
ksmps = 32
nchnls=2
0dbfs = 1
instr 1
aIn=vco2({amplitude},54.87)
aOut=juno60vcf(aIn,63,{resonance},1,1,4,0)
out(aOut,aOut)
endin'''
                    left, _, sr = render(Path(temporary), orchestra, 'i 1 0 2', 48000, 32, True)
                    audio = np.array(left)[sr:]
                    window = np.hanning(len(audio))
                    fundamental = abs(2*np.sum(audio*window*np.exp(
                        -2j*np.pi*54.87*np.arange(len(audio))/sr))/window.sum())
                    group.append(dict(input_amplitude=amplitude, law=law, panel=panel,
                                      fundamental_amplitude=float(fundamental)))
                for row in group:
                    row['gain_over_res_zero_db'] = float(20*np.log10(
                        row['fundamental_amplitude']/group[0]['fundamental_amplitude']))
                rows.extend(group)
    return rows, hashlib.sha256(PLUGIN.read_bytes()).hexdigest()


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('filter_captures', type=Path)
    parser.add_argument('lfo_captures', type=Path)
    args = parser.parse_args()
    self_check()
    source_hash = hashlib.sha256((PROJECT/'fixtures/voice.blue').read_bytes()).hexdigest()
    manifest = json.loads((PROJECT/'experiments/juno60_depth_curves/captures.json').read_text())
    for entry in manifest['captures']:
        root = args.lfo_captures if entry.get('root') == 'lfo' else args.filter_captures
        assert hashlib.sha256((root/entry['path']).read_bytes()).hexdigest() == entry['sha256']

    vcf = args.filter_captures/'Filter/VCF'
    _, reference = harmonics(vcf/'Juno 60 LPF=10.wav')
    cutoff, resonance = [], []
    static = {}
    for panel in [0, 2.5, 5, 7.5, 10]:
        f0, harmonic = harmonics(vcf/f'Juno 60 LPF={panel:g}.wav')
        static[panel] = (f0, harmonic)
        if panel == 10:
            continue  # reference is not an independently measured open pole
        frequency = f0*np.arange(1, len(harmonic)+1)
        ratio = harmonic/reference
        ceiling = 2000 if panel <= 5 else 10000
        valid = (harmonic > 1e-5) & (reference > 1e-4) & (frequency < ceiling)
        def residual(z):
            pole, gain = np.exp(z)
            predicted = gain*(1+(frequency/pole)**2)**-2
            return 20*np.log10(predicted[valid]/ratio[valid])
        fit = least_squares(residual, [np.log(max(12, panel**3*10)), 0],
                 bounds=([np.log(1), np.log(.95)], [np.log(100000), np.log(1.05)]))
        cutoff.append(dict(panel=panel, fundamental_hz=f0,
            estimated_pole_hz=float(np.exp(fit.x[0])),
            fitted_gain=float(np.exp(fit.x[1])),
            rmse_db=float(np.sqrt(np.mean(fit.fun*fit.fun))),
            harmonics_used=int(valid.sum()),
            production_command_hz=float(7.8*2**min(panel*1.66667, 14))))
    baseline = static[2.5][1][0]
    for panel in [0, 2.5, 5, 7.5, 10]:
        f0, harmonic = (static[2.5] if panel == 0 else
            harmonics(vcf/f'Juno 60 LPF2.5 Res={panel:g}.wav'))
        resonance.append(dict(panel=panel, fundamental_hz=f0,
            fundamental_amplitude=float(harmonic[0]),
            gain_over_res_zero_db=float(20*np.log10(harmonic[0]/baseline))))

    _, pulse = harmonics(args.lfo_captures/'LFO/PitchModulation/Juno 60 LFO 2.1 DCOmod 0.wav', 440, 9)
    orders = np.array([1, 3, 5, 7, 9])
    pulse = pulse[orders-1]
    modulation, traces = [], []
    for path in sorted((args.filter_captures/'LFO/FilterModulation').glob('*.wav')):
        sr, audio = read(path)
        onset, offset = held(audio, sr, .05)
        band = sosfiltfilt(butter(6, [300, 580], fs=sr, btype='bandpass', output='sos'), audio)
        phase = savgol_filter(np.unwrap(np.angle(hilbert(band))), 441, 3)
        inst = savgol_filter(np.gradient(phase)*sr/(2*np.pi), 441, 2)
        frames = []
        for center in np.arange(onset+.12, offset-.12, .01):
            ids = np.arange(int((center-.025)*sr), int((center+.025)*sr))
            h = coefficients(audio, phase, ids, orders)
            f0 = np.median(inst[ids])
            ratio = h/pulse
            pole = f0/np.sqrt(max(np.sqrt(1/ratio[0])-1, 1e-8))
            predicted = (1+(f0*orders/pole)**2)**-2
            error = np.sqrt(np.mean((20*np.log10(np.maximum(ratio, 1e-10)/predicted))[:3]**2))
            pole3, q3 = from_ratio(f0, ratio[1]/ratio[0], 3)
            frames.append([center-onset, f0, ratio[0], pole, error, pole3, q3])
        a = np.array(frames)
        common = (a[:,1] > 400) & (a[:,1] < 480) & (a[:,2] > .0002) & (a[:,2] < .98) & (a[:,4] < 3)
        ratio_valid = common & (a[:,2] > .002) & (a[:,6] > 1/9+.006) & (a[:,6] < .9) & np.isfinite(a[:,5])
        name = path.name
        panel = float(path.stem.split('Mod ')[-1])
        row = dict(file=name, panel=panel, freq_panel=2.5 if 'Freq=2.5' in name else 5,
                   amplitude_frames=int(common.sum()), ratio_frames=int(ratio_valid.sum()))
        if panel:
            row['amplitude_fit'] = fit_wave(a[common,0], a[common,3])
            row['ratio_fit'] = fit_wave(a[ratio_valid,0], a[ratio_valid,5])
            row['estimators_agree'] = abs(row['amplitude_fit']['half_range_octaves'] -
                                         row['ratio_fit']['half_range_octaves']) < .1
            row['production_anchor'] = False  # capture settings are not independently verified
        else:
            row['median_pole_amplitude_hz'] = float(np.median(a[common,3]))
            row['median_pole_ratio_hz'] = float(np.median(a[ratio_valid,5]))
            row['pitch_half_range_cents_2_98_percentiles'] = float(
                np.diff(np.percentile(1200*np.log2(a[:,1]), [2,98]))[0]/2)
        modulation.append(row)
        for index, frame in enumerate(a):
            traces.append(dict(file=name, seconds=frame[0], fundamental_hz=frame[1],
                fundamental_ratio=frame[2], amplitude_pole_hz=frame[3],
                harmonic_error_db=frame[4], ratio_pole_hz=frame[5],
                amplitude_valid=bool(common[index]), ratio_valid=bool(ratio_valid[index])))

    native, plugin_hash = native_resonance()
    for filename, rows in [('cutoff.csv', cutoff), ('resonance.csv', resonance),
                           ('native_resonance.csv', native), ('vcf_lfo_trace.csv', traces)]:
        with (DEST/filename).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    result = dict(project_sha256=source_hash, methods='Median coherent harmonics; four-pole magnitude model; independent fundamental-amplitude and harmonic-ratio inversions.',
        assumptions=['Test-plan settings rather than independently logged panel voltages.',
                     'Same source and recording gains; reference captures effectively open.',
                     'Equal linear poles, negligible resonance and other frequency-dependent losses.',
                     'Rounded-triangle LFO fit; high-depth phase coverage can be insufficient.'],
        cutoff=cutoff, resonance=resonance, vcf_lfo=modulation,
        native_resonance=native, plugin_sha256=plugin_hash)
    (DEST/'results.json').write_text(json.dumps(result, indent=2)+'\n')
    assert hashlib.sha256((PROJECT/'fixtures/voice.blue').read_bytes()).hexdigest() == source_hash
    print('PASS: capture hashes, analytic inversion check, production unchanged')
    for row in cutoff:
        print('FREQ', row['panel'], 'conditional pole', round(row['estimated_pole_hz'], 1))
    for row in modulation:
        if row['panel']:
            print('VCF LFO', row['panel'], row['freq_panel'],
                  round(row['amplitude_fit']['half_range_octaves'], 3),
                  round(row['ratio_fit']['half_range_octaves'], 3),
                  'estimators agree', row['estimators_agree'])


if __name__ == '__main__':
    main()
