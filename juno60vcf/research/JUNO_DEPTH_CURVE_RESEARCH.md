# Cutoff, resonance and modulation-depth calibration

## Measurement method

The capture analysis estimates a stage pole using
`|H(f)|=(1+(f/fc)^2)^-2` for four equal nonresonant stages. This fc is the
native opcode's stage-pole/self-oscillation convention; overall −3 dB is about
.435*fc at zero resonance. Confusing those definitions changes the calibration.

Static harmonics are divided by a FREQ-10 reference to reduce recording-chain
coloration. VCF LFO depth is estimated independently from fundamental amplitude
and third-harmonic/fundamental ratio. Both require negligible resonance and
comparable source/gain conditions; agreement does not prove those assumptions.
The [capture manifest](experiments/juno60_depth_curves/captures.json) records
pinned URLs and hashes. [Results](experiments/juno60_depth_curves/results.json)
retain assumptions and fit errors alongside the estimates.

## DCO and VCF depth

DCO hardware half-ranges were 94.40 cents at panel 5 and 223.18 at panel 10.
The reference soft knee gives 97.16 and 225 cents. Shape factors near 1.95/2.01
support the shared `tanh(2*x)/tanh(2)` rounded triangle at those depths.
Measurements below panel 5 are missing. Brass at panel 1.5 therefore uses an
estimated 7.912 cents, not a measured low-depth anchor. Loaded-pot/current/clock
conversion should be fitted together; blindly adding the missing pot load
reduces that value to 4.045 cents but spoils the measured midpoint agreement.

The service VCF LFO test specifies approximately 40–50 Hz to 4–5 kHz at FREQ
3.5, full depth, resonance 10, ENV/KEY 0. Endpoint ratios imply about ±3.161–3.483
octaves. TP19/other test-point volts alone are not an octave calibration.
The reference VCF uses the existing DCO soft-knee shape with separate maximum
±3.46 octaves:

| Panel | Linear ±3-octave law | Reference half-range, octaves |
| --- | ---: | ---: |
| 0 | 0 | 0 |
| 1.5 | .450 | .122 |
| 2.5 | .750 | .511 |
| 5 | 1.500 | 1.494 |
| 7.5 | 2.250 | 2.477 |
| 10 | 3.000 | 3.460 |

At FREQ 3.5, native endpoint renders gave 40.41 and 4894.00 Hz. This verifies
the implemented endpoint response, not the changing waveform or hardware
intermediate-depth calibration. The nonlinear calculation is cached on changes.

## Reusing existing shapes

Conditional VCF depth targets at panel 2.5/5/7.5 were .408/1.387/2.565 octaves,
using equal averages of the two estimators. At a common ±3.3-octave maximum:

| Shape | Predicted half-ranges | RMS error, octaves |
| --- | --- | ---: |
| Linear | .825/1.650/2.475 | .290 |
| Loaded pot | .688/1.303/2.063 | .335 |
| DCO soft knee | .488/1.425/2.363 | .128 |
| ENV transistor current | .527/1.444/2.370 | .136 |
| Loaded pot then ENV current | .378/1.057/1.908 | .425 |
| Cubic | .052/.413/1.392 | .904 |

Allowing only full-scale gain to vary, the soft knee fits 3.462 octaves with
.100-octave RMS error; ENV current fits 3.431 with .120. The composed
loaded-pot/current law fits intermediates more closely only by requiring
4.387 octaves, outside the service-derived endpoint range. Lower residual
alone is not sufficient evidence for a physically correct mapping.
The [comparison script](experiments/compare_juno60_slider_curves.py) generates
the complete alternatives, including LEVEL and timing curves, under
`build/research-results/`.

## FREQ and resonance limits

The single FREQ-3 tuning anchor does not determine full slider slope, loading
and baseline. Conflicting FREQ-5 captures prevent a unique calibration.
Keep exponential conversion of summed control voltage distinct from the
preceding pot law. The [VCF control note](JUNO_VCF_CONTROL_RESEARCH.md) discusses
the conditional FREQ-0 estimate and internal Nyquist guard.

A loaded-pot/current resonance candidate improves panel 2.5 gain from 5.69 to
2.39 dB versus 2.26 measured, but worsens middle/high matches. Recorded amplitude
is not a direct feedback-current measurement. Neither linear panel-to-K nor
self-oscillation onset is fully established by maximum-amplitude calibration.

## Sources and reproduction

- [Roland service notes](https://manuals.fdiskc.com/flat/Roland%20Juno-60%20Service%20Notes%20%28%20HI-RES%20%29.pdf), panel/CPU circuits and test programs.
- [Andy Harman hardware captures](https://github.com/pendragon-andyh/Juno60/tree/beab8655781db7dadf2bf9fa6e3d4b6514de3132), separate pitch/filter modulation and static VCF tests.
- [Capture test plan](https://github.com/pendragon-andyh/Juno60/blob/beab8655781db7dadf2bf9fa6e3d4b6514de3132/TestPlan/Juno60_ToneTestPlan.xlsx), requested settings rather than measured control voltages.

[research_juno60_depth_curves.py](experiments/research_juno60_depth_curves.py)
analyzes supplied recordings. [compare_juno60_slider_curves.py](experiments/compare_juno60_slider_curves.py)
uses the saved datasets and generates a new comparison under the build directory.
