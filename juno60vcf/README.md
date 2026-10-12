# juno60vcf

Csound 7 native opcode implementing a reduced Juno-60 VCF model: four buffered
linear OTA stages, TPT integrators, and saturating nonlinear resonance feedback.
Each instance owns its state and uses libsamplerate for internal medium-quality
sinc oversampling. No UDO or call-site interpolation is needed.

Imported from `~/work/blue/rhythmic/src` on October 12, 2026. The DSP implementation
is preserved; build paths, documentation, and test dependencies are adapted for
this repository. The independent UDO and its circuit/derivation references are
retained in [tests/reference/juno60_filter.udo](tests/reference/juno60_filter.udo).

## Opcode

```csound
aOut = juno60vcf(aIn, xCutoff, xResonance, xDrive [, iFeedbackScale, iOversample, iWarmStart])
```

- `aIn`: input audio; saturation levels follow the orchestra's `0dbfs`.
- `xCutoff`: Hz, audio or control rate; clamped to
  `0.1 .. 0.49*sr*iOversample` at the caller's sample rate. Pass the full cutoff
  command; the opcode guards its internal Nyquist frequency.
- `xResonance`: audio or control rate, clamped to `0 .. 1`. Self-oscillation
  starts near 0.952 with the model's provisional feedback calibration.
- `xDrive`: input gain, audio or control rate; negative values clamp to zero.
- `iFeedbackScale`: saturation-level multiplier, default 1.
- `iOversample`: 1, 2, or 4; omitted/0 selects 4. Use 2 to reduce CPU cost with
  more aliasing at high cutoff, or 1 to disable internal oversampling.
- `iWarmStart`: default 1. Initialize an unexcited filter above oscillation onset
  near its settled oscillation state; use 0 for a cold start.

K-rate controls are interpolated over each host block. Audio-rate controls are
resampled together with the input. Converters are primed with silence for
consistent startup with small `ksmps`. Warm initialization uses harmonic balance
and introduces no ongoing noise or per-note pre-roll. Below onset, an unexcited
filter remains silent; cold mode retains zero state until excited. Retain the
instance and gate a VCA after the filter to preserve oscillation between notes.

The imported 2x/4x medium-sinc path was measured with 94 caller samples of impulse
delay at 44.1/48/96 kHz and `ksmps` 1/32/64/128. For an external VCA, align its
control with `delay(aVca, 94/sr)` and keep the voice alive to flush the delay and
control tail. At 1x, converter delay is zero.

The model assumes ideal buffers and linear filter-stage OTAs. Driven input and
output feedback mix inside the same saturation:
`u = x - K*L*tanh((y - c*x)/L)`, with `c ≈ 0.307762`. At panel maximum `K=4.2`,
the default `L=2.217661865*0dbfs` sets nominal settled oscillation amplitude to
`0dbfs`, matching a pulse of +/-`0dbfs` under Roland's relative TP4 service
calibration. This is a common relative scale, not an input limiter. Hardware
recordings are still needed to validate the full model and startup behavior.
Oversampling reduces nonlinear aliasing; ultrasonic oscillation is removed by
the output converter, and higher nonlinear harmonics can still alias.

## Build and verify

From the repository root, follow the [build instructions](../README.md#build):

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target juno60vcf --parallel
ctest --test-dir build -R '^juno60vcf$' --output-on-failure
```

The Csound SDK must match the host's version and precision. Csound is accessed
through the plugin function table and is not linked directly. Filter state and
calculations use `cs_double`; audio buffers use `cs_float`. Explicit conversion
to 32-bit `float` is confined to the dynamically linked libsamplerate boundary.

The checks compare the native core against the included independent UDO and
analytic responses. They cover oversampling, cutoff bounds, silence,
oscillation, nonlinear drive, block sizes, `0dbfs` scaling, sample-accurate note
boundaries, and invalid arguments. Temporary WAV files and isolated plugin
search paths ensure they exercise the binary passed to the script.

## Audition and benchmark

On macOS, from the repository root:

```sh
CS_USER_PLUGINDIR="$PWD/build/juno60vcf" csound --opcode-lib=build/juno60vcf/juno60vcf.dylib juno60vcf/examples/Juno60Native.csd
python3 juno60vcf/tests/check_juno60vcf.py build/juno60vcf/juno60vcf.dylib --benchmark
```

Use `.so` on Linux or `.dll` on Windows, adjusting for the build configuration
directory when applicable. The example contains cutoff, resonance, drive, and
self-oscillation sweeps. Add `--smacro:LEVEL_REFERENCES=1` to the Csound command
to play the pulse, noise, and resonance level references instead.

An already installed opcode with the same name may shadow a new build.
`CS_USER_PLUGINDIR` above points Csound at the new module. The checks additionally
isolate `OPCODE7DIR` and `OPCODE7DIR64`. To use the library in Blue, copy it to
your Csound opcode directory and restart Blue. On macOS, replace an installed
library by copying to a temporary filename and renaming it over the destination
to avoid stale code-signature caching.
