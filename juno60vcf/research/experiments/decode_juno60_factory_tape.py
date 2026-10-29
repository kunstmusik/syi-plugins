#!/usr/bin/env python3
"""Decode Synthmania's bank-A tape capture; report stored bytes, not panel positions.

python3 experiments/decode_juno60_factory_tape.py captures/public/factory-bank-A.wav
Independent decoder of the published tape-format facts; no emulator code.
This is a measurement of one hashed capture, not a general tape librarian.
"""
from research_paths import RESULTS
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

PROJECT = Path(__file__).resolve().parents[1]
DEST = RESULTS / 'juno60_drum_pitch'
SHA = '30887e52fb1cd84610a9e93f387247ea417f1d5d95e7223189c893866e3fad8f'
CONTROLS = ['vcf_env', 'vcf_lfo', 'vcf_kybd', 'vca_level', 'env_attack',
            'env_release', 'env_decay', 'env_sustain', 'vcf_freq', 'dco_noise',
            'dco_sub', 'vcf_res', 'dco_pwm', 'lfo_rate', 'dco_lfo', 'lfo_delay']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    args = parser.parse_args()
    assert hashlib.sha256(args.recording.read_bytes()).hexdigest() == SHA
    rate, raw = wavfile.read(args.recording)
    assert rate == 22050 and raw.dtype == np.uint8 and raw.ndim == 1
    audio = raw.astype(float)-128
    edges = np.flatnonzero((audio[:-1] <= 0) & (audio[1:] > 0))
    crossings = edges-audio[edges]/(audio[edges+1]-audio[edges])
    periods = np.diff(crossings)
    times = (crossings[:-1]+crossings[1:])/(2*rate)
    keep = (times > .3) & (periods > 5) & (periods < 23)
    carrier_bits, times = (periods[keep] < 12.6).astype(int), times[keep]
    boundaries = np.r_[0, np.flatnonzero(np.diff(carrier_bits))+1, len(carrier_bits)]
    runs = [(int(carrier_bits[a]), b-a, float(times[a]))
            for a, b in zip(boundaries[:-1], boundaries[1:])]
    start = next(i for i, (bit, cycles, _) in enumerate(runs)
                 if bit == 0 and cycles >= 32)
    # Round carrier-cycle counts to bit counts. Framing, sequence and every
    # checksum below independently validate the result despite tape glitches.
    stream = np.concatenate([np.full(round(cycles/(7 if bit else 4)), bit)
                             for bit, cycles, _ in runs[start:]])
    assert stream[:9].tolist() == [0]*8+[1]
    words = stream[9:9+64*19*11].reshape(64, 19, 11)
    assert np.all(words[:,0] == 1)
    assert np.all(words[:,1:,:3] == [1,1,0])
    values = words[:,:,3:] @ (2**np.arange(8))
    assert np.array_equal(values[:,1], np.arange(64))
    checksums = np.sum(values[:,1:], axis=1) % 256
    assert np.all(checksums == 0), checksums
    payload = values[:,2:18]
    rows = []
    for index in range(56):
        switch = payload[56+index//8,2*(index%8):2*(index%8)+2]
        rows.append(dict(patch=(index//8+1)*10+index%8+1,
                         **dict(zip(CONTROLS, map(int,payload[index]))),
                         switch_byte_1=int(switch[0]), switch_byte_2=int(switch[1])))
    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST/'factory_bank_A_bytes.csv').open('w', newline='') as output:
        writer = csv.DictWriter(output, rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    metadata = dict(source_url='https://www.synthmania.com/Roland%20Juno-60/Audio/Roland%20Juno-60%20factory%20programs%20group%201.wav',
        source_sha256=SHA, format_source='https://wolfeffect.wordpress.com/juno-60-tape-format-reverse-engineered/',
        first_header_seconds=runs[start][2], blocks=64, valid_checksums=64,
        patch_78=rows[-1],
        limitations='Stored ADC/DAC bytes are voltages, not linear physical slider percentages. Switch-byte interpretation needs independent verification; raw bytes are preserved. The performance may have different calibration/settings from the tape.')
    (DEST/'factory_tape.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print('PASS: 64 framing markers, sequence numbers and checksums; '+str(rows[-1]))


if __name__ == '__main__':
    main()
