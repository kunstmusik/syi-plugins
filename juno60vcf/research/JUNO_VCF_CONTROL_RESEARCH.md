# VCF control conversion and hardware comparisons

## Sum modulation before exponentiation

The IR3109 control path supports a summed octave-domain expression:

```text
fc(t) = f_reference * 2**(FREQ + KEY + LFO + polarity*D(panel)*E(t))
```

E is raw envelope voltage normalized to a reference; D is depth in octaves.
ENV, LFO and key tracking are summed before exponential conversion. Neither
adding ENV in Hz nor taking log(ENV) follows the documented circuit. The native
filter accepts the final Hz command; these mappings belong to the caller.

The reference fixture uses 7.8 Hz and 1.66667 octaves per FREQ panel unit.
FREQ 3 requests 249.602 Hz versus the 248 Hz service anchor. With ENV at full
scale, the assumed 12 octaves gives 31,948.8 Hz versus the approximate 30 kHz
service target. The latter would require 11.9092 octaves if 7.8 Hz were independently
known. One service point cannot determine the baseline, slope and depth jointly.

## Cutoff ceiling and oversampling

Cutoff is clamped below the internal Nyquist frequency:
`0.1 <= fc <= .49*caller_sr*oversample`. The UDO's sr is already multiplied
by its oversampling factor. A caller-Nyquist ceiling incorrectly discards
ultrasonic commands that can still affect audible response.

For autonomous oscillation commanded to 31,948.807 Hz, measured residual output:

| Output rate | 2x RMS dBFS | 4x RMS dBFS |
| --- | ---: | ---: |
| 44.1 kHz | −40.51 | −72.60 |
| 48 kHz | −40.67 | −125.82 |

At 2x, peaks near 7647.52 Hz and 153.54 Hz respectively match third-harmonic
folding around the internal rate. At 4x/44.1 kHz, a residual near 16,655.97 Hz is
consistent with fifth-harmonic folding. These software measurements motivate
the 4x default. Oversampling does not eliminate every nonlinear alias or raise
the output Nyquist frequency. An absent ultrasonic fundamental after conversion
is not evidence that the internal filter failed to oscillate.

[The control script](experiments/measure_juno60_control_mapping.py) generates
commands, output RMS and residual peaks under `build/research-results/` and
leaves fundamental/pitch-error fields empty above output Nyquist. Native checks
also compare high-tone small-signal responses with independent equations.

## ENV depth current driver

The service schematic routes reconstructed control voltage through R21/C12,
R135 and VR12 into TR36, whose collector biases the depth OTA. R21/C12 conditions
changes of the depth setting, not raw ENV. A reduced PNP model solves:

```text
Vcontrol = Rseries*IE + VT*log(1+IE/ISE)
IC = beta/(beta+1)*IE
D(panel) = Dmax*IE(Vcontrol)/IE(5V)
```

Nominal assumptions: Rseries=18k, beta=200, VT=25.6926 mV at 25 C, and
IC=100 uA at VBE≈.57 V. These give ISE=2.32901192e-14 A and IE(5V)=244.840 uA.
The VBE value is a typical datasheet reading, not a measurement of the recorded
unit. At panel 4, this law gives 3.90985 octaves instead of linear depth 4.8.
Zero and the provisional 12-octave maximum are preserved.

The reference voice caches its eight-step solve until the control changes;
the standalone example evaluates it at initialization. Independent bracketed
root checks cover both sweep directions, endpoints and clamping.
Rseries=13–23k and VBE=.54–.63 V produce panel-4 depth 3.785–3.974 octaves;
this is sensitivity analysis, not a guaranteed hardware tolerance.
See [driver results](experiments/juno60_env_depth/).

## Drum pitch evidence

The first isolated passage of Synthmania factory patch 78 provides a useful
pitch trajectory. Its note, key-on/off events, baseline and exact performance
settings are not independently known. MP3 onset is not electrical key-on.

| Comparison | Initial slope, oct/s | Fall between onset-relative windows, octaves |
| --- | ---: | ---: |
| Hardware passage | −8.881 | .7045 |
| Linear-depth reference | −11.615 | .8806 |
| Nominal transistor driver | −9.461 | .7158 |

The driver comparison assumes a 105 ms hold inferred from a later slope bend.
The initial slope still differs by 6.5%; a small windowed-fall error is not a
complete match. Native command tracking after the 94-sample delay had median
error −.331 cents, so extra filter lag did not explain the initial discrepancy.

Two exploratory linear-depth fits were close: 3.660 octaves with Decay 1.50175 s,
or 4.8 octaves with Decay 2.04778 s. Unknown tuning and key events prevent a
unique calibration. Independent PWM-capture decay rates 2.749–3.015/s bracket
the reference rate 4.2/1.50175=2.797/s. Depth and decay must remain separate.
[Drum results](experiments/juno60_drum_pitch/) preserve fit parameters and
trajectories; [public measurements](experiments/juno60_public_measurements/)
record source hashes, estimator settings and onset limitations.

A separate conditional FREQ-0 estimate is about 12.12 Hz from ratios of
54.88 Hz fundamentals in static hardware captures. It assumes common gain,
flat HPF and four equal poles. It is not an isolated oscillator baseline and
does not establish a replacement cutoff law.

## Sources and capture limits

- [Roland Juno-60 service notes](https://manuals.fdiskc.com/flat/Roland%20Juno-60%20Service%20Notes%20%28%20HI-RES%20%29.pdf), printed pp.5/7/9 and adjustment procedures.
- [Juno-6 service notes](https://www.synfo.nl/servicemanuals/Roland/JUNO-6_SERVICE_NOTES.pdf), exponential converter; panel calibration is not interchangeable with Juno-60.
- [AS3109 datasheet](https://www.alfatriode.lv/eng/sc/AS3109.pdf), replacement-chip frequency sensitivity.
- [2SA1015 datasheet](https://datasheet.octopart.com/2SA1015-Y-Toshiba-datasheet-13698240.pdf), typical PNP characteristics.
- [Synthmania Juno-60](https://www.synthmania.com/juno-60.htm), factory examples and cassette capture.
- [Hardware capture catalog](experiments/juno60_public_recordings.json), source URLs, hashes and recording limitations.

Polyphonic DCO demonstrations do not directly reveal raw ENV. Unknown gain,
chorus, retrofit behavior, note overlap and MP3 encoding constrain what can be
inferred. Use isolated recordings with identifiable settings to fit depth,
decay curvature and time laws independently.
