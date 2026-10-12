#!/usr/bin/env python3
"""Compare the native filter to the UDO; optionally time 16 simultaneous voices."""
import argparse
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import struct
import tempfile
import time

UDO = (Path(__file__).resolve().parent / "reference/juno60_filter.udo").read_text()


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

def rms(values):
    return math.sqrt(sum(x*x for x in values) / len(values))

def frequency(values, rate):
    crossings = [i - values[i] / (values[i+1] - values[i])
                 for i in range(len(values)-1) if values[i] <= 0 < values[i+1]]
    assert len(crossings) > 2
    return rate * (len(crossings)-1) / (crossings[-1]-crossings[0])

def reference(factor):
    result = re.sub(r"oversample\(\d+,\s*1,\s*1\)",
                    f"oversample({factor}, 1, 1)", UDO)
    # The warm-start control guard belongs to the sinc-converted UDO, not
    # the unresampled mathematical core used for the 1x comparison.
    result = re.sub(r"kWarmWait init \d+", f"kWarmWait init {128*factor if factor > 1 else 0}", result)
    return result


def csd(body, definitions="", rate=48000, block=32, duration=2, score=None, dbfs=1):
    return f"""<CsoundSynthesizer>
<CsOptions>
-d -m0 --sample-accurate
</CsOptions>
<CsInstruments>
sr = {rate}
ksmps = {block}
nchnls = 1
0dbfs = {dbfs}
seed 1234
{definitions}
instr Check
{body}
out(aOut)
endin
</CsInstruments>
<CsScore>
{score or f'i "Check" 0 {duration}'}
e
</CsScore>
</CsoundSynthesizer>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", type=Path)
    parser.add_argument("csound", nargs="?", default="csound")
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    plugin = args.plugin.resolve()
    assert plugin.is_file(), plugin
    with tempfile.TemporaryDirectory(prefix="juno60vcf-check-") as temp:
        directory = Path(temp)
        # Isolate the explicit binary from installed opcodes of the same name.
        env = dict(os.environ, CS_USER_PLUGINDIR=str(directory),
                   OPCODE7DIR=str(directory), OPCODE7DIR64=str(directory))

        def run(text, audio=True, success=True):
            source, output = directory / "check.csd", directory / "check.wav"
            source.write_text(text)
            command = [args.csound, f"--opcode-lib={plugin}"]
            command += ["-W", "--format=double", "-o", str(output)] if audio else ["-n"]
            start = time.perf_counter()
            result = subprocess.run(command + [str(source)], capture_output=True,
                                    text=True, timeout=90, env=env)
            elapsed = time.perf_counter() - start
            if success:
                assert result.returncode == 0, result.stderr
            else:
                assert result.returncode != 0, result.stderr
                return result.stderr
            return samples(output)[0] if audio else elapsed

        # Same discrete equations, no resampling: exercise the nonlinear solve,
        # audio-rate modulation, cutoff bounds, and input drive simultaneously.
        signal = """aIn = oscili(0.15, 110) + random:a(-0.01, 0.01)
aCutoff = expseg:a(80, 1, 18000, 1, 80)
aRes = linseg:a(0, 1, 1, 1, 0)
aDrive = expseg:a(0.25, 1, 8, 1, 0.25)
"""
        udo = run(csd(signal + "aOut = juno60_filter(aIn, aCutoff, aRes, aDrive)",
                      reference(1)))
        native = run(csd(signal + "aOut = juno60vcf(aIn, aCutoff, aRes, aDrive, 1, 1)"))
        error = max(abs(x-y) for x, y in zip(udo, native))
        assert error < 2e-11, error
        print(f"PASS: native core agrees with UDO, maximum error {error:.3g}", flush=True)

        # Put the native core behind Csound's own converters to isolate the
        # DSP port from the plugin's continuous SRC startup policy.
        for factor in (2, 4):
            wrapper = f"""opcode native_reference(aIn, aCutoff, aRes, aDrive):a
  oversample({factor}, 1, 1)
  aOut = juno60vcf(aIn, aCutoff, aRes, aDrive, 1, 1)
  xout aOut
endop
"""
            udo = run(csd(signal + "aOut = juno60_filter(aIn, aCutoff, aRes, aDrive)",
                          reference(factor)))
            native = run(csd(signal + "aOut = native_reference(aIn, aCutoff, aRes, aDrive)",
                             wrapper))
            error = max(abs(x-y) for x, y in zip(udo, native))
            assert error < 2e-6, error
            print(f"PASS: {factor}x Csound oversampling parity, maximum error {error:.3g}",
                  flush=True)

        for factor in (1, 2, 4):
            zero = run(csd(f"aIn = 0\naOut = juno60vcf(aIn, 1000, 1, 1, 1, {factor}, 0)",
                           duration=0.1))
            assert max(abs(x) for x in zero) == 0
            for res in (0, 0.8):
                body = f"aIn = oscili(0.0001, 100)\naOut = juno60vcf(aIn, 1000, {res}, 1, 1, {factor})"
                values = run(csd(body))
                g = math.tan(math.pi*1000/(factor*48000))
                omega = math.tan(math.pi*100/(factor*48000))
                cascade = (g/complex(g, omega))**4
                compensation = (1.5/48.5) / ((68/10)*(1.5/101.5))
                expected = abs((1 + compensation*4.2*res)*cascade/(1 + 4.2*res*cascade))
                gain = rms(values[-24000:])/(0.0001/math.sqrt(2))
                assert math.isclose(gain, expected, rel_tol=0.002), (factor, gain, expected)
            print(f"PASS: {factor}x internal oversampling, silence and analytic sine gain",
                  flush=True)

        # A high input tone distinguishes a 31.949 kHz pole from the old caller
        # ceiling. Check the independent four-pole response and tangent guard
        # at each processing rate, including a command far above that guard.
        for rate in (44100, 48000, 96000):
            for factor in (1, 2, 4):
                tone = min(16000, .3*rate)
                for command in (31948.807453, 1e6):
                    body = (f"aIn = oscili(.0001, {tone})\n"
                            f"aOut = juno60vcf(aIn, {command}, 0, 1, 1, {factor})")
                    values = run(csd(body, rate=rate, duration=.4))
                    cutoff = min(command, .49*rate*factor)
                    ratio = math.tan(math.pi*tone/(rate*factor)) / math.tan(math.pi*cutoff/(rate*factor))
                    expected = (1 + ratio*ratio)**-2
                    gain = rms(values[-rate//5:])/(.0001/math.sqrt(2))
                    assert math.isclose(gain, expected, rel_tol=.003), (rate,factor,command,gain,expected)
            print(f"PASS: ultrasonic cutoff response and internal Nyquist guard, sr={rate}", flush=True)

        high_signal = "aIn = oscili(.1, 110)\naCutoff = expseg:a(80, .2, 35000, .2, 80)\naRes = .8\naDrive = 1\n"
        for factor in (2, 4):
            wrapper = f"""opcode native_reference(aIn, aCutoff, aRes, aDrive):a
  oversample({factor}, 1, 1)
  aOut = juno60vcf(aIn, aCutoff, aRes, aDrive, 1, 1)
  xout aOut
endop\n"""
            udo = run(csd(high_signal + "aOut = juno60_filter(aIn,aCutoff,aRes,aDrive)", reference(factor), duration=.4))
            native = run(csd(high_signal + "aOut = native_reference(aIn,aCutoff,aRes,aDrive)", wrapper, duration=.4))
            assert max(abs(x-y) for x,y in zip(udo,native)) < 2e-6
        print("PASS: UDO/native parity through ultrasonic cutoff sweeps", flush=True)

        default = run(csd("aIn = oscili(.0001, 16000)\naOut = juno60vcf(aIn, 31948.8, 0, 1)", duration=.1))
        explicit = run(csd("aIn = oscili(.0001, 16000)\naOut = juno60vcf(aIn, 31948.8, 0, 1, 1, 4)", duration=.1))
        zero = run(csd("aIn = oscili(.0001, 16000)\naOut = juno60vcf(aIn, 31948.8, 0, 1, 1, 0)", duration=.1))
        assert default == explicit == zero
        print("PASS: omitted/zero oversampling selects 4x", flush=True)

        # Warm state starts at the limit cycle, with no input or noise source.
        # Compare ports without SRC, then exercise the default at every factor.
        warm_signal = "aIn = 0\naCutoff = 1000\naRes = 1\naDrive = 1\n"
        udo = run(csd(warm_signal + "aOut = juno60_filter(aIn, aCutoff, aRes, aDrive)",
                      reference(1), duration=.1))
        native = run(csd(warm_signal + "aOut = juno60vcf(aIn, aCutoff, aRes, aDrive, 1, 1)",
                        duration=.1))
        assert max(abs(x-y) for x,y in zip(udo,native)) < 2e-11
        for factor in (1,2,4):
            for res in (.953,.96,1):
                values = run(csd(f"aIn = 0\naOut = juno60vcf(aIn, 1000, {res}, 1, 1, {factor})"))
                first, last = rms(values[:1200]), rms(values[-24000:])
                assert .7*last < first < 1.2*last and last > .003, (factor,res,first,last)
                assert max(abs(x) for x in values) < 1.1
                # Independent quadrature of the tanh fundamental.
                lo,hi = 0.,1.
                for _ in range(40):
                    amplitude = (lo+hi)/2
                    gain = sum(math.tanh(amplitude*math.cos((i+.5)*math.pi/128)) *
                               math.cos((i+.5)*math.pi/128) for i in range(128)) * 2/(128*amplitude)
                    if gain > 4/(4.2*res): lo = amplitude
                    else: hi = amplitude
                expected = 2.217661865*(lo+hi)/2/math.sqrt(2)
                assert math.isclose(last, expected, rel_tol=.03), (factor,res,last,expected)
        below = run(csd("aIn = 0\naOut = juno60vcf(aIn, 1000, .95, 1)", duration=.1))
        assert max(abs(x) for x in below) == 0
        rising = run(csd("aIn = 0\nkRes = linseg:k(.8, .05, .8, .001, 1)\naOut = juno60vcf(aIn, 1000, kRes, 1)",duration=.15))
        assert max(abs(x) for x in rising[:2000]) == 0 and rms(rising[-2400:]) > .05
        print("PASS: warm default, cold opt-out, near-onset amplitude, and resonance rise", flush=True)

        # Independently solve the nonlinear DC equilibrium by bisection.
        # Large driven inputs distinguish mixing inside the OTA from a linear
        # boost outside it; check both polarities and every SRC mode.
        for factor in (1, 2, 4):
            for driven in (0.01, 0.5, 4, -4):
                compensation = (1.5/48.5) / ((68/10)*(1.5/101.5))
                lo, hi = sorted((compensation*driven, driven))
                for _ in range(60):
                    y = (lo + hi)/2
                    error = y - driven + 3.36*2.217661865*math.tanh((y-compensation*driven)/2.217661865)
                    if error < 0: lo = y
                    else: hi = y
                expected = (lo + hi)/2
                values = run(csd(f"aIn = {driven/2}\naOut = juno60vcf(aIn, 1000, 0.8, 2, 1, {factor})"))
                measured = statistics.mean(values[-24000:])
                assert math.isclose(measured, expected, rel_tol=2e-6, abs_tol=2e-8), (factor, driven, measured, expected)
        print("PASS: nonlinear input/feedback mixing, DC equilibrium and drive", flush=True)

        rings = {}
        for rate, cutoff, scale, factor in ((44100, 248, 1, 2), (48000, 248, 1, 2),
                                           (96000, 1000, 1, 4), (48000, 248, 2, 2)):
            body = f"""aGate = linseg:a(1, 0.02, 1, 1/sr, 0)
aIn = random:a(-0.01, 0.01) * aGate
aOut = juno60vcf(aIn, {cutoff}, 1, 1, {scale}, {factor})"""
            values = run(csd(body, rate=rate))
            first, last = rms(values[-rate:-rate//2]), rms(values[-rate//2:])
            assert 0.65*scale < last < 0.8*scale, last
            assert math.isclose(first, last, rel_tol=0.02), (first, last)
            pitch = frequency(values[-rate//2:], rate)
            assert abs(pitch/cutoff - 1) < 0.02, pitch
            assert max(abs(x) for x in values) < 1.2*scale
            rings[rate, cutoff, scale] = last
            print(f"PASS: bounded {factor}x self-oscillation at {rate} Hz, "
                  f"RMS {last:.6f}, pitch {pitch:.3f} Hz", flush=True)
        assert math.isclose(rings[48000, 248, 2]/rings[48000, 248, 1], 2, rel_tol=0.01)

        for block in (1, 7, 32, 256):
            body = """aIn = random:a(-1, 1)
kCutoff = expseg:k(0.001, 0.05, sr, 0.05, 0.001)
kRes = linseg:k(-1, 0.05, 2, 0.05, -1)
aOut = juno60vcf(aIn, kCutoff, kRes, 8)"""
            values = run(csd(body, block=block, duration=0.1))
            assert max(abs(x) for x in values) < 20
        print("PASS: k-rate controls, bounds, and ksmps 1/7/32/256", flush=True)

        body = "aIn = oscili(0.1 * 0dbfs, 110)\naOut = juno60vcf(aIn, 1000, 0.8, 2)"
        normalized = run(csd(body, dbfs=1))
        scaled = run(csd(body, dbfs=32768))
        # Csound normalizes floating-point WAV samples by the orchestra's 0dbfs.
        assert max(abs(x-y) for x, y in zip(normalized, scaled)) < 2e-6
        print("PASS: 0dbfs normalization", flush=True)

        body = "aIn = 0.1\naOut = juno60vcf(aIn, 1000, 0, 1)"
        values = run(csd(body, duration=0.02, score='i "Check" 0.000125 0.01425'))
        assert max(abs(x) for x in values[:6]) == 0
        assert max(abs(x) for x in values[690:]) == 0
        assert max(abs(x) for x in values) > 0.01
        print("PASS: sample-accurate start/end masking", flush=True)

        body = "aIn = 0\naOut = juno60vcf(aIn, 1000, 1, 1, 1, 3)"
        error = run(csd(body, duration=0.01), audio=False, success=False)
        assert "oversampling must be" in error
        print("PASS: invalid oversampling rejected", flush=True)
        error = run(csd("aIn = 0\naOut = juno60vcf(aIn, 1000, 1, 1, 1, 2, 2)",
                        duration=.01), audio=False, success=False)
        assert "warm start must be" in error

        if args.benchmark:
            body = """aIn = vco2(0.1, p4)
aCutoff = expseg:a(200, p3/2, 8000, p3/2, 200)
aRes = 0.8
aDrive = 1
"""
            score = "\n".join(f'i "Check" 0 4 {110*2**(voice/12)}' for voice in range(16))
            timings = {"UDO": [], "native": []}
            for _ in range(3):
                for label, call, definitions in (
                    ("UDO", "juno60_filter(aIn, aCutoff, aRes, aDrive)", reference(4)),
                    ("native", "juno60vcf(aIn, aCutoff, aRes, aDrive)", "")):
                    timings[label].append(run(csd(body + f"aOut = {call}", definitions,
                                                 score=score), audio=False))
            slow, fast = (statistics.median(timings[label]) for label in ("UDO", "native"))
            print(f"BENCHMARK: 16 voices, 4 seconds, 48 kHz, 4x medium sinc, "
                  f"median of 3 runs: UDO {slow:.3f}s, native {fast:.3f}s; "
                  f"{slow/fast:.2f}x speedup", flush=True)
    print("All juno60vcf checks passed.", flush=True)


if __name__ == "__main__":
    main()
