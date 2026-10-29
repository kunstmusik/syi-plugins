# Relative level and output-path calibration

## Shared pulse and oscillation reference

Roland's TP4 service target is 4 V peak-to-peak after the voice VCA. It is not
an isolated filter-core voltage. With a common fixed VCA reference, use a pulse
at +/-1 and settled self-oscillation at nominal amplitude 1 as a relative scale.
At K=4.2, harmonic balance gives A/L=.4509253714 and L=2.217661865.
This is the opcode's default saturation scale, multiplied by 0dbfs and feedback
scale; it is not a per-preset normalizer or input limiter.

Digital band-limiting and SRC cause pulse edge overshoot. At the open-filter
4x reference, pulse p-p measured 2.356, median plateau 1.000 and RMS .9975;
oscillation p-p measured 2.001 and RMS .7071. Compare plateau to sine peak and
check the expected square/sine RMS ratio rather than fitting the model to edge
overshoot. An earlier independent .25 saturation scale produced a roughly
19 dB relative mismatch. The [level script](experiments/measure_juno60_levels.py)
generates calibration tables for the selected build under `build/research-results/`;
the earlier mismatch is a historical comparison, not a current-build measurement.

## Signal path

```text
DCO mixture -> per-voice VCF -> envelope/gate VCA -> voice sum
 -> common HPF -> global patch LEVEL -> chorus/dry mix -> output
```

A pre-filter HPF does not attenuate autonomous oscillation generated afterward
and changes driven nonlinear behavior. The Juno-60 uses flat setting 0 and three
first-order HPF settings. The Juno-106 bass-boost/bypass arrangement is a different
circuit. Ignoring switch resistance and finite input impedance:

```text
R = 470k || 33k = 30834.99 ohms
C = 22 nF, 10 nF, 4.7 nF
fc = 1/(2*pi*R*C) = 234.61, 516.15, 1098.19 Hz
```

At 248 Hz, expected oscillation RMS reductions are about 2.78/7.27/13.15 dB.
Software probes agreed within 1%; the cutoff values are circuit estimates.

## Source, LEVEL and chorus gain

For normalized panel p, the reduced loaded-pot law is
`u=p/(1+(50/47)*p*(1-p))`. It reaches exact zero and gives .170909 at panel 2.
Using this voltage as SUB/NOISE amplitude omits source switching losses and
current-transfer details. Independent per-voice noise also differs from a common
hardware noise source under polyphony.

Patch LEVEL is global, distinct from the voice BA662. The reference mapping
`10**((panel-5)*2.4/20)` maps −5/0/+5 to −24/−12/0 dB. The 2.4 dB/unit slope
remains provisional. A related µPC1252 device and resistor estimate suggest
about 21.82 dB across the fader, without establishing the complete original
transfer. Do not infer that all factory sounds should have equal loudness.

The chorus schematic has a fixed dry path and switched wet path. Relative to
bypass, the reference uses dry=1 and wet=47/39 from the 47k/39k input resistors.
Absolute BBD gain and combined-mode calibration still require measurement.

## Recording protocol

Use a fixed interface/master gain, HPF 0, chorus off, LEVEL +5, ENV mode,
minimum attack/decay/release, sustain 10 and no pitch/filter modulation.
Record five-second held notes with silence between takes and repeat across voices:

1. Pulse only, 50% duty, FREQ 10 and resonance 0; then saw only.
2. SUB and NOISE separately at panel 10, 5 and 2.
3. All DCO sources off, resonance 10, FREQ 3; allow oscillation to settle.
4. Repeat oscillation with each HPF and LEVEL 0/−5.
5. Repeat pulse with chorus off/I/II/combined at unchanged gains.

Do not normalize, compress or EQ individual takes. Noise p-p depends on
bandwidth and observation duration and should not be equated with pulse RMS.
The [level script](experiments/measure_juno60_levels.py) performs software probes;
[full-voice checks](experiments/check_juno60_voice.py) exercise the common output.

## Sources

- [Roland service notes](https://medias.audiofanzine.com/files/roland-juno-60-service-notes-472222.pdf), TP4 adjustment, CPU and chorus schematics.
- [Owner's manual](https://cdn.roland.com/assets/media/pdf/JUNO-60_OM.pdf), patch LEVEL and HPF operation.
- [HPF circuit analysis](https://electricdruid.net/highpass-filters-in-synths/), Juno-60/106 distinction.
- [µPC1252HA2 reference](https://www.datasheetarchive.com/datasheet/UPC1252HA2/NEC?term=upc1252&version=1), related-device gain estimate.
