#!/usr/bin/env python3
"""Run independent transfer/oscillation checks for fixtures/Juno60Filter.csd.

Uses Csound 7 and Python's standard library; all probe WAVs are temporary.
Run from any directory: python3 experiments/check_juno60_filter.py
"""
import math
from pathlib import Path
import re
import struct
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = (PROJECT / "fixtures/Juno60Filter.csd").read_text()
ORCHESTRA = SOURCE.split("<CsInstruments>", 1)[1].split("instr FilterSweep", 1)[0]
FACTOR = int(re.search(r"oversample\((\d+),", ORCHESTRA).group(1))


def samples(path):
    data = path.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    pos, chunks = 12, {}
    while pos + 8 <= len(data):
        name, size = struct.unpack_from("<4sI", data, pos)
        chunks[name] = data[pos + 8:pos + 8 + size]
        pos += 8 + size + size % 2
    fmt, channels, rate = struct.unpack_from("<HHI", chunks[b"fmt "])
    bits = struct.unpack_from("<H", chunks[b"fmt "], 14)[0]
    assert (fmt, channels, bits) == (3, 1, 64)
    raw = chunks[b"data"]
    values = struct.unpack(f"<{len(raw)//8}d", raw)
    assert all(math.isfinite(x) for x in values), "Nonfinite output"
    return values, rate


def render(directory, body, rate=48000, duration=2, block=32):
    orchestra = re.sub(r"^sr = .*", f"sr = {rate}", ORCHESTRA, flags=re.M)
    orchestra = re.sub(r"^ksmps = .*", f"ksmps = {block}", orchestra, flags=re.M)
    orchestra = orchestra.replace("nchnls = 2", "nchnls = 1")
    csd, wav = directory / "check.csd", directory / "check.wav"
    csd.write_text(f"""<CsoundSynthesizer>
<CsOptions>
-d -m0
</CsOptions>
<CsInstruments>
{orchestra}
seed 1234
instr Check
{body}
out(aOut)
endin
</CsInstruments>
<CsScore>
i "Check" 0 {duration}
e
</CsScore>
</CsoundSynthesizer>
""")
    result = subprocess.run(["csound", "-W", "--format=double", "-o", str(wav),
                             str(csd)], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    values, actual_rate = samples(wav)
    assert actual_rate == rate and abs(len(values) - duration*rate) <= block
    return values


def rms(values):
    return math.sqrt(sum(x*x for x in values) / len(values))


def frequency(values, rate):
    crossings = [i - values[i] / (values[i+1] - values[i])
                 for i in range(len(values)-1) if values[i] <= 0 < values[i+1]]
    assert len(crossings) > 2
    return rate * (len(crossings)-1) / (crossings[-1]-crossings[0])


def main():
    with tempfile.TemporaryDirectory(prefix="juno60-check-") as temporary:
        directory = Path(temporary)
        zero = render(directory, "aIn = 0\naCutoff = 1000\naRes = 1\naDrive = 1\naOut = juno60_filter(aIn, aCutoff, aRes, aDrive, 1, 0, 0)")
        assert max(abs(x) for x in zero) == 0
        print("PASS: cold opt-out gives exact silence at maximum resonance", flush=True)
        warm = render(directory, "aIn = 0\naCutoff = 1000\naRes = 1\naDrive = 1\naOut = juno60_filter(aIn, aCutoff, aRes, aDrive)")
        assert rms(warm[:1200]) > .7*rms(warm[-24000:]) > .04
        print("PASS: warm default oscillates immediately without excitation", flush=True)
        # Sinc control startup must not initialize a below-onset limit cycle
        # or overestimate a near-onset amplitude. Check several caller blocks.
        for rate, block in ((44100, 1), (48000, 32), (96000, 256)):
            for resonance in (.95, .953):
                output = render(directory, f"aIn = 0\naCutoff = 1000\naRes = {resonance}\naDrive = 1\naOut = juno60_filter(aIn, aCutoff, aRes, aDrive)", rate, .25, block)
                if resonance == .95:
                    assert max(abs(x) for x in output) == 0, (rate, block)
                else:
                    early, late = rms(output[:int(.025*rate)]), rms(output[-int(.025*rate):])
                    assert .65*late < early < 1.2*late and .008*(2.217661865/.25) < late < .011*(2.217661865/.25), (rate, block, early, late)
        print("PASS: below-onset silence and near-onset warm amplitude across rates/blocks", flush=True)

        # Compare to independently calculated four-pole bilinear response,
        # including feedback. The tiny sine keeps the OTA in its linear region.
        for resonance in (0, 0.8):
            output = render(directory, f"""aIn = oscili(0.0001, 100)
aCutoff = 1000
aRes = {resonance}
aDrive = 1
aOut = juno60_filter(aIn, aCutoff, aRes, aDrive)""")
            g = math.tan(math.pi * 1000 / (FACTOR*48000))
            omega = math.tan(math.pi * 100 / (FACTOR*48000))
            cascade = (g / complex(g, omega)) ** 4
            compensation = (1.5/48.5) / ((68/10)*(1.5/101.5))
            expected = abs((1 + compensation*4.2*resonance)*cascade / (1 + 4.2*resonance*cascade))
            measured = rms(output[-24000:]) / (0.0001/math.sqrt(2))
            assert math.isclose(measured, expected, rel_tol=0.002), (measured, expected)
            print(f"PASS: sine gain at resonance {resonance}: {measured:.6f}", flush=True)

        ring_levels = {}
        for rate, cutoff, scale in ((44100, 248, 1), (48000, 248, 1),
                                    (96000, 1000, 1), (48000, 248, 2)):
            output = render(directory, f"""aGate = linseg:a(1, 0.02, 1, 1/sr, 0)
aIn = random:a(-0.01, 0.01) * aGate
aCutoff = {cutoff}
aRes = 1
aDrive = 1
aOut = juno60_filter(aIn, aCutoff, aRes, aDrive, {scale})""", rate)
            first, last = rms(output[-rate:-rate//2]), rms(output[-rate//2:])
            assert 0.65*scale < last < 0.8*scale, last
            assert math.isclose(first, last, rel_tol=0.02), (first, last)
            pitch = frequency(output[-rate//2:], rate)
            assert abs(pitch/cutoff - 1) < 0.02, pitch
            assert max(abs(x) for x in output) < 1.2*scale
            ring_levels[rate, cutoff, scale] = last
            print(f"PASS: bounded ring, sr={rate}, cutoff={cutoff}, "
                  f"scale={scale}: RMS={last:.6f}, pitch={pitch:.3f} Hz", flush=True)
        assert math.isclose(ring_levels[48000, 248, 2] / ring_levels[48000, 248, 1],
                            2, rel_tol=0.01)

        decay = render(directory, """aGate = linseg:a(1, 0.02, 1, 1/sr, 0)
aIn = random:a(-0.01, 0.01) * aGate
aCutoff = 1000
aRes = 0.9
aDrive = 1
aOut = juno60_filter(aIn, aCutoff, aRes, aDrive)""")
        assert rms(decay[-24000:]) < 1e-8
        print("PASS: burst decays below self-oscillation onset", flush=True)

        stress = render(directory, """aIn = random:a(-1, 1)
aCutoff = expseg:a(0.001, 1, sr, 1, 0.001)
kRes = linseg:k(-1, 1, 2, 1, -1)
aRes = interp(kRes)
aDrive = 8
aOut = juno60_filter(aIn, aCutoff, aRes, aDrive)""")
        assert max(abs(x) for x in stress) < 20
        print("PASS: finite output under wide cutoff/resonance sweeps and drive 8", flush=True)
    print("All Juno-60 filter checks passed.")


if __name__ == "__main__":
    main()
