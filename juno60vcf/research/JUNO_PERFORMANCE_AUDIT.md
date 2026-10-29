# Filter and reference-voice performance

These are saved offline software benchmarks, not real-time capacity guarantees.
The [raw results](experiments/juno60_performance_audit.json) record individual
runs, source/binary hashes, settings and parity errors. Platform: arm64 Csound 7,
double samples, 44.1 kHz, ksmps 64, isolated plugin paths and no audio device.
Wall time includes process startup. Small full-voice differences fall within
run-to-run variation.

## Cost attribution

| Probe | Baseline | Candidate | Interpretation |
| --- | ---: | ---: | --- |
| VCA only, 32 instances × 20 s | .1982 s | filter2: .1641 s | 17.2% local saving |
| Six stress voices, four-second notes | 1.8585 s | VCF bypass: .0790 s | VCF dominates; bypass changes the sound |
| Six stress voices, alternating runs | 1.7383 s | filter2 VCA: 1.7308 s | .4%; no reliable whole-voice gain |
| Chorus I, eight seconds | .5087 s | Inline BLEP: .4993 s | 1.8%; small return for duplicated code |
| Combined chorus, eight seconds | .5020 s | One shared BBD: .2784 s | 44.6%, fixed mode only |

A separate 16-voice, four-second, 48 kHz/ksmps 32, 4x benchmark measured native
3.187 s versus UDO 12.589 s, median of three runs. It includes startup and
voice creation and should not be compared directly with the 44.1 kHz matrix.

## VCA equivalence

The 10.78 ms conditioning network has direct feedthrough plus one pole:

```text
p = exp(-1/(sr*tau))
H(z) = [1-(37/49)*p-(12/49)*p*z^-1] / [1-p*z^-1]
aVca = filter2(aEnv, 2, 1, 1-(37/49)*p, -(12/49)*p, -p)
```

Across ENV/impulse/random probes, 44.1/48/96 kHz and ksmps 1/32/64/128,
maximum absolute differences were 9.55e-12 for filter2, 9.54e-12 for biquad
and 1.39e-16 for ntrpol. These are numerical equivalence measurements, not a
claim of bit identity. Keep the external VCA's 94-sample delay and tail lifetime.
Moving amplitude ahead of the nonlinear filter changes the sound.

## Native filter opportunities

The existing buffer path converts cs_float scratch arrays to libsamplerate
float arrays and back, followed by further copying. Profiling and reducing
those passes is a plausible optimization; no speedup is established by this
inspection alone. Preserve exact float-conversion boundaries, interleaved control
timing and startup behavior when evaluating it.

The cutoff cache already avoids repeated tan for unchanged commands. Moving
cutoff to k-rate, reducing oversampling, relaxing the nonlinear solve or
bypassing constant-control conversion changes behavior and needs a separate
error/sound-quality comparison.

## Chorus state and shared channels

Identical BBD input/clock in a fixed combined mode permits one line feeding
two decode/noise paths. Live switching changes the contract: the two lines
may carry different phase/history after I/II. A naive shared branch produced
up to .3554 output difference in a mode-change probe and stops advancing the
skipped line's state. Fixed-mode parity does not justify a general replacement.

Opposite triangle modulation can use negation (tested error 1.67e-16), but it
did not show a reliable performance gain. Preserve filters, independent hiss
and remaining BLEP corrections unless a measured equivalence supports removal.

Always-on output and voice instrument numbers need not match. Publish/read a
shared synth identifier for LFO channels. Isolated tests that substitute one
instrument number into both blocks can conceal a generated-orchestra mismatch.

## Reproduction

[audit_juno60_performance.py](experiments/audit_juno60_performance.py) accepts
`--section all`, `check`, `vca`, `voice`, `chorus`, or `followup` and a repeat
count. New measurements go to the build directory; saved results are unchanged.
The [full-voice checks](experiments/check_juno60_voice.py) and
[LFO checks](experiments/check_juno60_lfo.py) cover the connected caller paths.

Opcode semantics: [filter2](https://csound.com/manual/opcodes/filter2/),
[ntrpol](https://csound.com/manual/opcodes/ntrpol/),
[vco2](https://csound.com/manual/opcodes/vco2/).
