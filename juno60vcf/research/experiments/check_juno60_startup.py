#!/usr/bin/env python3
"""Probe the FactoryPatch instrument in fixtures/Juno60Filter.csd, outside fixtures/voice.blue.

python3 experiments/check_juno60_startup.py
Outputs CSV metrics, source/binary hashes, and a 24-bit audition WAV.
"""
from research_paths import PLUGIN, RESULTS
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import wave

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = (PROJECT / 'fixtures/Juno60Filter.csd').read_text()
ORCHESTRA = SOURCE.split('<CsInstruments>', 1)[1].split('</CsInstruments>', 1)[0]
DEST = RESULTS / 'juno60_startup_calibrated'


def read_stereo(path):
    data = path.read_bytes()
    pos, chunks = 12, {}
    while pos+8 <= len(data):
        name, size = struct.unpack_from('<4sI', data, pos)
        chunks[name] = data[pos+8:pos+8+size]
        pos += 8+size+size%2
    fmt, channels, rate = struct.unpack_from('<HHI', chunks[b'fmt '])
    bits = struct.unpack_from('<H', chunks[b'fmt '], 14)[0]
    assert (fmt, channels, bits) == (3, 2, 64)
    values = struct.unpack(f"<{len(chunks[b'data'])//8}d", chunks[b'data'])
    assert all(math.isfinite(x) for x in values)
    return values[::2], values[1::2], rate


def rms(values):
    return math.sqrt(sum(x*x for x in values)/len(values))


def render(directory, orchestra, score, rate, block, native=False):
    orchestra = re.sub(r'^sr = .*', f'sr = {rate}', orchestra, flags=re.M)
    orchestra = re.sub(r'^ksmps = .*', f'ksmps = {block}', orchestra, flags=re.M)
    orchestra = orchestra.replace('0dbfs = 1', '0dbfs = 1\nseed 1234')
    path, output = directory/'probe.csd', directory/'probe.wav'
    path.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0 --sample-accurate
</CsOptions>
<CsInstruments>
{orchestra}
</CsInstruments>
<CsScore>
{score}
e
</CsScore>
</CsoundSynthesizer>
''')
    env = dict(os.environ, CS_USER_PLUGINDIR=str(directory),
               OPCODE7DIR=str(directory), OPCODE7DIR64=str(directory))
    command = ['csound', '-W', '--format=double', '-o', str(output),
               '--omacro:STARTUP_TAPS=1']
    if native:
        command.append(f'--opcode-lib={PLUGIN}')
    result = subprocess.run(command+[str(path)], env=env, capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return read_stereo(output)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    rows, audition = [], []
    with tempfile.TemporaryDirectory(prefix='juno60-startup-') as temporary:
        directory = Path(temporary)
        for engine in ('udo', 'native'):
            orchestra = ORCHESTRA
            if engine == 'native':
                old = 'aFiltered = juno60_filter(aTestInput, aCutoff, aResonance, aDrive, 1, iThermalNoise, iWarmStart)'
                assert orchestra.count(old) == 1
                orchestra = orchestra.replace(old,
                    'aFiltered = juno60vcf(aTestInput, aCutoff, aResonance, aDrive, 1, 4, iWarmStart)')
            for patch in (74, 78):
                for mode in (range(6) if engine == 'udo' else (0,1,2,5)):
                    warm = 6 if mode == 2 else 2 if mode == 4 else 0
                    release = .002+11.998*(.7 if patch == 74 else .6)**3
                    hold = 1.5
                    duration = warm+hold+release+.25
                    raw, gated, rate = render(directory, orchestra,
                        f'i "FactoryPatch" 0 {duration} {patch} {mode} -120 {warm} {hold} 60',
                        44100, 64, engine == 'native')
                    start = warm*rate
                    note = gated[start:]
                    onset = next((index/rate for index, value in enumerate(note)
                                  if abs(value) >= .001), None)
                    row = dict(engine=engine, patch=patch, mode=mode, rate=rate,
                               warm_seconds=warm, burst_gain_db=-120 if mode in (1,2) else '',
                               raw_peak=max(abs(x) for x in raw),
                               gated_peak=max(abs(x) for x in gated),
                               first20ms_rms=rms(note[:int(.02*rate)]),
                               onset_above_minus60_db_seconds=onset if onset is not None else '',
                               pre_gate_raw_rms=rms(raw[start-int(.1*rate):start]) if warm else '')
                    rows.append(row)
                    assert max(abs(x) for x in raw) < 1.5, row
                    assert max(abs(x) for x in gated[-int(.1*rate):]) < 1e-10, row
                    if mode == 0:
                        assert row['raw_peak'] == row['gated_peak'] == 0, row
                    else:
                        assert row['gated_peak'] > .01 and onset is not None, row
                    if warm:
                        assert max(abs(x) for x in gated[:start]) == 0, row
                        assert row['pre_gate_raw_rms'] > .03 and onset < .02, row
                    if mode == 5:
                        assert onset < .02 and row['first20ms_rms'] > .01, row
                    if engine == 'udo' and mode == 5:
                        audition += list(note)+[0.0]*int(.4*rate)
                    print(f"PASS: {engine}, patch {patch}, mode {mode}: peak "
                          f"{row['gated_peak']:.6g}, onset {onset}, "
                          f"first 20ms RMS {row['first20ms_rms']:.6g}", flush=True)

        # Observe the generator directly without SRC to check density scaling.
        noise_orchestra = re.sub(r'oversample\(\d+, 1, 1\)', 'oversample(1, 1, 1)', ORCHESTRA)
        noise_orchestra = noise_orchestra.replace('aOut[kIndex] = kY4',
                                                  'aOut[kIndex] = aThermalNoise[kIndex]')
        noise_orchestra += '''
instr NoiseProbe
  aIn = 0
  aCutoff = 248
  aRes = 1
  aDrive = 1
  aNoise = juno60_filter(aIn, aCutoff, aRes, aDrive, 1, 1)
  out(aNoise, aNoise)
endin
'''
        density_checks = []
        resistance = 1/(1/1500+1/100000)+1/(1/1500+1/47000)
        density = math.sqrt(4*1.380649e-23*298.15*resistance)
        vt = 1.380649e-23*298.15/1.602176634e-19
        for rate in (44100, 48000, 96000):
            noise, _, _ = render(directory, noise_orchestra, 'i "NoiseProbe" 0 1', rate, 32)
            expected = 2.217661865*density*math.sqrt(rate/2)/(2*vt)
            measured = rms(noise)
            assert math.isclose(measured, expected, rel_tol=.015), (rate, measured, expected)
            density_checks.append(dict(rate=rate, expected_rms=expected, measured_rms=measured))
            print(f'PASS: resistor-noise RMS, sr={rate}: {measured:.9g}, expected {expected:.9g}', flush=True)

        # Independently integrate the linear noise transfer. Noise is at the
        # OTA differential input: H_eta = -K*P/(1+K*P), not the mixer transfer.
        filtered_orchestra = noise_orchestra.replace(
            'aOut[kIndex] = aThermalNoise[kIndex]', 'aOut[kIndex] = kY4')
        filtered_orchestra = filtered_orchestra.replace('aRes = 1\n', 'aRes = 0.8\n')
        filtered_checks = []
        for rate, factor in ((44100,1), (96000,1), (44100,2), (96000,2)):
            probe_orchestra = filtered_orchestra.replace('oversample(1, 1, 1)',
                                                         f'oversample({factor}, 1, 1)')
            noise, _, _ = render(directory, probe_orchestra, 'i "NoiseProbe" 0 4', rate, 32)
            measured = rms(noise[rate:])
            local_rate = rate*factor
            sigma = 2.217661865*density*math.sqrt(local_rate/2)/(2*vt)
            warp = math.tan(math.pi*248/local_rate)
            bins, power_sum = 16384, 0.0
            for index in range(bins):
                frequency = (index+.5)*local_rate/(2*bins)
                cascade = (warp/complex(warp, math.tan(math.pi*frequency/local_rate)))**4
                response = 3.36*cascade/(1+3.36*cascade)
                power_sum += abs(response)**2
            expected = sigma*math.sqrt(power_sum/bins)
            assert math.isclose(measured, expected, rel_tol=.12), (rate, measured, expected)
            # Noise above host Nyquist is negligible at this 248 Hz pole.
            filtered_checks.append(dict(rate=rate, oversampling=factor,
                                        measured_rms=measured, expected_rms=expected))
            print(f'PASS: differential-input noise transfer, sr={rate}, OS={factor}: '
                  f'{measured:.9g}, expected {expected:.9g}', flush=True)

    with (DEST/'patches.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = dict(source_sha256=hashlib.sha256(SOURCE.encode()).hexdigest(),
                    native_sha256=hashlib.sha256(PLUGIN.read_bytes()).hexdigest(),
                    temperature_kelvin=298.15, equivalent_resistance_ohms=resistance,
                    differential_density_volts_per_sqrt_hz=density,
                    density_checks=density_checks,
                    filtered_noise_checks=filtered_checks,
                    audition='UDO warm default, mode 5; patch 74 followed by 78; no noise, preroll or normalization')
    (DEST/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    with wave.open(str(DEST/'Factory74-78.wav'), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(3)
        stream.setframerate(44100)
        pcm = bytearray()
        for value in audition:
            pcm.extend(round(value*8388607).to_bytes(3, 'little', signed=True))
        stream.writeframes(pcm)
    print(f'All startup checks passed; results in {DEST}', flush=True)


if __name__ == '__main__':
    main()
