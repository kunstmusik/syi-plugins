#!/usr/bin/env python3
"""Measure the compiled opcode. Requires Csound 7, NumPy and Matplotlib.

python3 experiments/measure_juno60vcf.py [--plugin build/juno60vcf/juno60vcf.dylib]
Results compare software with explicit equations, not recorded hardware.
"""
from research_paths import PLUGIN, RESULTS
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from check_juno60_filter import samples, frequency

PROJECT = Path(__file__).resolve().parents[1]
SR = 48000
NFFT = 262144
IMPULSE = 1e-5
OFFSET = 4800
COMPENSATION = (1.5/48.5) / ((68/10)*(1.5/101.5))


def db(value):
    return 20 * np.log10(np.maximum(np.abs(value), 1e-15))


def rms(value):
    return float(np.sqrt(np.mean(np.square(value))))


def transfer(freq, cutoff, resonance, factor=None):
    # Four equal linear poles with negative global feedback; the current
    # opcode uses cutoff as each stage's pole frequency, not overall f-3dB.
    ratio = freq / cutoff if factor is None else (
        np.tan(np.pi * freq / (SR * factor)) /
        np.tan(np.pi * cutoff / (SR * factor)))
    cascade = (1 + 1j * ratio) ** -4
    return (1 + COMPENSATION * 4.2 * resonance) * cascade / (1 + 4.2 * resonance * cascade)


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=PLUGIN)
    parser.add_argument("--csound", default="csound")
    parser.add_argument("--output", type=Path, default=RESULTS / "juno60_measurements_compensated")
    args = parser.parse_args()
    plugin = args.plugin.resolve()
    assert plugin.is_file(), plugin
    args.output.mkdir(parents=True, exist_ok=True)
    response_rows, summary, dynamics, distortion, startup = [], [], [], [], []
    spectra, envelopes = {}, {}
    with tempfile.TemporaryDirectory(prefix="juno60-measure-") as temp:
        directory = Path(temp)
        # --opcode-lib alone may lose to a same-name installed opcode.
        env = dict(os.environ, CS_USER_PLUGINDIR=str(directory),
                   OPCODE7DIR=str(directory), OPCODE7DIR64=str(directory))

        def render(source, cutoff=1000, resonance=0, factor=2, duration=2):
            csd, wav = directory / "probe.csd", directory / "probe.wav"
            csd.write_text(f"""<CsoundSynthesizer>
<CsOptions>
-d -m0
</CsOptions>
<CsInstruments>
sr = {SR}
ksmps = 32
nchnls = 1
0dbfs = 1
seed 1234
instr Probe
{source}
aOut = juno60vcf(aIn, {cutoff:.12g}, {resonance:.12g}, 1, 1, {factor}, 0)
out(aOut)
endin
</CsInstruments>
<CsScore>
f1 0 65536 10 1
i "Probe" 0 {duration:.12g}
e
</CsScore>
</CsoundSynthesizer>
""")
            result = subprocess.run([args.csound, f"--opcode-lib={plugin}", "-W",
                                     "--format=double", "-o", str(wav), str(csd)],
                                    capture_output=True, text=True, timeout=90, env=env)
            if result.returncode:
                raise RuntimeError(result.stderr)
            values, rate = samples(wav)
            assert rate == SR and len(values) >= round(duration * SR)
            return np.asarray(values)

        # Silent lead-in lets resampled controls settle before the impulse.
        # No window: the complete decaying impulse response is the measurement.
        freq = np.fft.rfftfreq(NFFT, 1 / SR)
        for cutoff, resonances in ((1000, (0, 0.5, 0.8, 0.9, 0.94)),
                                   (248, (0,)), (992, (0,)),
                                   (5000, (0,)), (12000, (0,))):
            for resonance in resonances:
                for factor in (1, 2, 4):
                    signal = render(f"aIn = mpulse({IMPULSE}, 0, 0.1)", cutoff,
                                    resonance, factor, (OFFSET + NFFT) / SR)
                    response = np.fft.rfft(signal[OFFSET:OFFSET + NFFT]) / IMPULSE
                    assert rms(signal[-SR//4:]) < 1e-12, "Impulse tail did not settle"
                    spectra[cutoff, resonance, factor] = response
                    ideal = transfer(freq, cutoff, resonance, factor)
                    analog = transfer(freq, cutoff, resonance)
                    band = (freq >= 10) & (freq <= min(15000, cutoff * 4)) & (db(ideal) > -80)
                    error = float(np.max(np.abs(db(response[band]) - db(ideal[band]))))
                    assert error < 0.06, (cutoff, resonance, factor, error)
                    peak = int(np.argmax(np.abs(response)))
                    half = np.flatnonzero(np.abs(response) <= abs(response[0]) / np.sqrt(2))
                    at_cutoff = float(np.interp(cutoff, freq, db(response)))
                    phase_error = np.unwrap(np.angle(response / ideal))
                    delay_band = (freq >= 20) & (freq <= 2000)
                    delay = -np.polyfit(freq[delay_band], phase_error[delay_band], 1)[0] / (2*np.pi)
                    summary.append(dict(cutoff_hz=cutoff, resonance=resonance, oversample=factor,
                                        dc_gain_db=float(db(response[0])), peak_hz=float(freq[peak]),
                                        peak_gain_db=float(db(response[peak])), gain_at_cutoff_db=at_cutoff,
                                        first_minus3db_relative_dc_hz=float(freq[half[0]]),
                                        digital_equation_max_error_db=error,
                                        extra_src_delay_ms=float(delay * 1000)))
                    # Keep logarithmically spaced bins plus the resonance neighborhood.
                    indices = np.unique(np.r_[0, np.searchsorted(freq, np.geomspace(10, 22000, 360)),
                                               np.searchsorted(freq, [cutoff, 20000]),
                                               np.arange(max(0, peak-20), peak+21)])
                    for i in indices:
                        response_rows.append(dict(cutoff_hz=cutoff, resonance=resonance,
                                                  oversample=factor, frequency_hz=float(freq[i]),
                                                  measured_gain_db=float(db(response[i])),
                                                  measured_phase_rad=float(np.angle(response[i])),
                                                  digital_gain_db=float(db(ideal[i])),
                                                  analog_equal_pole_gain_db=float(db(analog[i]))))
            print(f"Measured frequency response: cutoff {cutoff} Hz", flush=True)

        # Decay/growth around onset, followed by a sustained autonomous ring.
        gate = "aGate = linseg:a(0, 0.1, 0, 1/sr, 1, 0.02, 1, 1/sr, 0)"
        for cutoff in (248, 992):
            for resonance in (0.9, 0.95, 4/4.2, 0.96, 0.98, 1):
                signal = render(gate + "\naIn = random:a(-0.01, 0.01) * aGate",
                                cutoff, resonance, duration=8)
                tail = signal[-SR:]
                level = rms(tail)
                pitch = frequency(tail, SR) if level > 1e-8 else None
                dynamics.append(dict(cutoff_hz=cutoff, resonance=resonance,
                                     rms_0p3_0p5s=rms(signal[int(.3*SR):int(.5*SR)]),
                                     rms_last_second=level, tail_peak=float(np.max(abs(tail))),
                                     tail_crossing_hz=pitch))
                if resonance == 1:
                    assert level > 0.01 and abs(pitch/cutoff - 1) < .005
            print(f"Measured autonomous ringing: cutoff {cutoff} Hz", flush=True)

        # One-second coherent sine spectrum after one-second settling. Harmonic
        # powers 2..10; no window or spectral leakage from the 1000 Hz source.
        for resonance in (0, 0.8):
            for amplitude in (0.001, 0.01, 0.1, 1, 4):
                signal = render(f"aIn = oscili({amplitude}, 1000, 1)", resonance=resonance)
                tail = signal[-SR:]
                spectrum = np.fft.rfft(tail) * (2 / SR)
                harmonics = np.abs(spectrum[np.arange(1, 11) * 1000])
                thd = np.linalg.norm(harmonics[1:]) / harmonics[0]
                distortion.append(dict(resonance=resonance, input_peak=amplitude,
                                       input_peak_dbfs=float(db(amplitude)),
                                       fundamental_gain_db=float(db(harmonics[0]/amplitude)),
                                       output_rms=rms(tail), thd_2_to_10_db=float(db(thd)),
                                       second_harmonic_dbc=float(db(harmonics[1]/harmonics[0])),
                                       third_harmonic_dbc=float(db(harmonics[2]/harmonics[0]))))
                if resonance == 0:
                    assert thd < 1e-6, thd
        print("Measured sine amplitude/distortion sweep", flush=True)

        # These are experimental excitations, not a calibrated hardware noise
        # model. Record the uniform random gain AND its theoretical input RMS.
        for cutoff in (50, 248, 992):
            for gain_db in (None, -120, -100, -75, -60):
                source = "aIn = 0" if gain_db is None else (
                    f"aGate = linseg:a(0, 0.1, 0, 1/sr, 1)\n"
                    f"aIn = random:a(-1, 1) * ampdbfs({gain_db}) * aGate")
                signal = render(source, cutoff, 1, duration=8)
                blocks = signal[:len(signal)//960*960].reshape(-1, 960)
                envelope = np.sqrt(np.mean(blocks**2, axis=1))
                steady = rms(signal[-SR:])
                hits = np.flatnonzero(envelope >= .9 * steady) if steady > 1e-8 else []
                onset = float(hits[0] * .02 + .01 - .1) if len(hits) else None
                startup.append(dict(cutoff_hz=cutoff, uniform_noise_gain_dbfs= gain_db,
                                    theoretical_input_rms_dbfs=None if gain_db is None else gain_db-10*np.log10(3),
                                    tail_rms=steady, first_20ms_rms_window_center_at_90pct_tail_s=onset))
                envelopes[cutoff, gain_db] = envelope
                if gain_db is None:
                    assert np.max(abs(signal)) == 0
            print(f"Measured noise sensitivity: cutoff {cutoff} Hz", flush=True)

    for name, rows in (("frequency_response", response_rows), ("response_summary", summary),
                       ("ringing", dynamics), ("distortion", distortion), ("startup", startup)):
        write_csv(args.output / f"{name}.csv", rows)
    version = subprocess.run([args.csound, "--version"], capture_output=True, text=True).stderr
    metadata = dict(sample_rate=SR, ksmps=32, dbfs=1, warm_start=0, impulse_peak=IMPULSE,
                    impulse_delay_s=.1, response_samples=NFFT,
                    default_oversample=2, scale=1, drive=1, random_seed=1234,
                    plugin_path=plugin.name, plugin_sha256=hashlib.sha256(plugin.read_bytes()).hexdigest(),
                    csound_version=version.splitlines()[:3], numpy_version=np.__version__,
                    input_compensation=COMPENSATION, hardware_recordings=False)
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    fig, axes = plt.subplots(2, 2, figsize=(13, 9), layout="constrained")
    ax = axes[0, 0]
    for resonance in (0, .5, .8, .9, .94):
        ax.semilogx(freq[1:], db(spectra[1000, resonance, 2][1:]), label=f"res {resonance:g}")
    ax.set(xlim=(20, 16000), ylim=(-85, 40), title="Measured small-signal response (2x, pole 1 kHz)",
           xlabel="Frequency (Hz)", ylabel="Gain (dB)")
    ax.legend(fontsize=9)

    ax = axes[0, 1]
    res = np.linspace(0, .95, 100)
    ax.plot(res, db(1/(1+4.2*res)), label="Previous uncompensated equation")
    # Schematic reading: R24=10k, stage feedback=68k, R5=47k,
    # R3=100k, R1=R2=1.5k. Ideal-stage/zero-input-current approximation.
    alpha = COMPENSATION
    ax.plot(res, db((1+alpha*4.2*res)/(1+4.2*res)), "--",
            label=f"Corrected equation (c={alpha:.3f}); dots measured")
    chosen = [s for s in summary if s["cutoff_hz"] == 1000 and s["oversample"] == 2]
    ax.scatter([s["resonance"] for s in chosen], [s["dc_gain_db"] for s in chosen], s=20)
    ax.set(xlabel="Opcode resonance", ylabel="Low-frequency gain (dB, normalized at res=0)",
           title="Input path corrected: measured against the circuit approximation", ylim=(-15, 1))
    ax.legend(fontsize=8)

    ax = axes[1, 0]
    for factor in (1, 2, 4):
        ax.semilogx(freq[1:], db(spectra[12000, 0, factor][1:]), label=f"Measured {factor}x")
    ax.semilogx(freq[1:], db(transfer(freq[1:], 12000, 0)), "k--", label="Analog equal-pole equation")
    ax.set(xlim=(1000, 22000), ylim=(-35, 0), xlabel="Frequency (Hz)", ylabel="Gain (dB)",
           title="High-cutoff warping and converter response (res=0)")
    ax.legend(fontsize=9)

    ax = axes[1, 1]
    for gain in (-120, -100, -75, -60):
        env = envelopes[248, gain]
        ax.plot(np.arange(len(env))*.02 + .01 - .1, db(env), label=f"Noise gain {gain} dBFS")
    ax.set(xlim=(0, 1.5), ylim=(-130, -15), xlabel="Time after excitation (s)", ylabel="Output RMS (dBFS)",
           title="Startup depends on chosen excitation (248 Hz, res=1)")
    ax.legend(fontsize=9)
    for ax in axes.flat:
        ax.grid(True, which="both", alpha=.2)
    fig.suptitle("juno60vcf measurements — 48 kHz; hardware calibration pending", fontsize=16)
    fig.savefig(args.output / "overview.png", dpi=160)
    fig.savefig(args.output / "overview.svg")
    plt.close(fig)
    print(f"Measurements and plots saved to {args.output}")


if __name__ == "__main__":
    main()
