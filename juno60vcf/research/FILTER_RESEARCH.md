# Filter circuit and numerical model

The model is a four-stage buffered IR3109-style OTA cascade with a saturating
BA662-style resonance path. Each stage has a 240 pF capacitor. Filter stages
are linear and buffers ideal; stage loading, offsets and nonlinear stage OTAs
remain outside this reduced model.

## Feedback and input compensation

The schematic mixes both the driven input and filter output into the resonance
OTA. With input x, output y, resonance gain K and saturation level L:

```text
u = x - K*L*tanh((y-c*x)/L)
c = (1.5/48.5) / ((68/10)*(1.5/101.5)) ≈ 0.307762
```

The resistor ratios use R1/R2=1.5k, R3=100k, R5=47k, R24=10k and 68k stage
feedback, neglecting OTA input loading. Compensation acts inside the same
nonlinearity as feedback. An output limiter or a separate linear boost would
not implement this circuit approximation.

For a four-stage small-signal cascade P, the transfer is
`(1+c*K)*P/(1+K*P)`. At a 1 kHz stage pole and 2x oversampling, the compensated
low-frequency gains at resonance .5/.8/.9/.94 were −5.50/−6.62/−6.89/−6.98 dB,
versus −9.83/−12.79/−13.59/−13.89 dB without that path.
[measure_juno60vcf.py](experiments/measure_juno60vcf.py) compares the compiled
module with the discrete equations and generates response tables and an overview
plot under `build/research-results/`. The uncompensated values above summarize
the historical baseline; the current script measures the selected plugin.

## TPT discretization and scalar solve

For each stage, `g=tan(pi*fc/internal_sr)`, `G=g/(1+g)`,
`y=G*u+(1-G)*z`, and `zNext=2*y-z`. The complete cascade is `y=G^4*u+S`.
Solving for `d=y-c*x` gives:

```text
d + G^4*K*L*tanh(d/L) = G^4*x + S - c*x
```

The derivative is at least 1 and the root lies between zero and the right-hand
side. Safeguarded Newton steps stay inside this bracket. This regulates the
internal feedback rather than concealing divergent states behind clipping.
Cutoff coefficient caching avoids repeated tangent evaluation for an unchanged
command. Control interpolation and oversampling timing are part of the behavior.

The active [native checks](../tests/check_juno60vcf.py) compare the core with an
independent UDO and analytic small-signal/DC responses. The full
[reference UDO](fixtures/Juno60Filter.csd) also supplies factory and noise probes.
These checks validate the implementation of the approximation, not a complete
match to original hardware.

## Startup and amplitude

Small-signal oscillation begins at K=4; panel maximum is provisionally K=4.2.
At maximum, tanh harmonic balance gives `A/L=0.4509253714`.
`L=2.217661865*0dbfs` therefore gives nominal amplitude `A=0dbfs`, sharing the
relative scale of a pulse at +/-`0dbfs`. See [level calibration](JUNO_LEVEL_RESEARCH.md).

Warm startup approximates a settled oscillation at an output zero crossing.
Three Newton steps and four state assignments avoid per-note pre-roll and
ongoing excitation. Below onset an unexcited filter stays silent. Cold mode
keeps exact-zero state until input excites it. This is a practical startup
assumption; continuously powered hardware voices have different histories.
[check_juno60_startup.py](experiments/check_juno60_startup.py) generates cold/warm
startup measurements and metadata under `build/research-results/`.

## Noise experiment and limits

The standalone UDO optionally models differential resistor noise from
`R1||R3 + R2||R5`. At 298.15 K the density is about 6.95 nV/sqrt(Hz).
For thermal voltage VT, normalized RMS is
`L*sqrt(4*k*T*R*internal_sr/2)/(2*VT)`. Noise enters the OTA differential input,
not the DCO mixer. Its linear transfer is `-K*P/(1+K*P)`.
This experiment is disabled by default and is not in the native opcode.

Replacement-chip noise/distortion specifications do not directly specify a
complete vintage instrument's noise gain. Recording node, load, bandwidth,
voltage scale, trim, temperature and source impedances still require calibration.

## Sources

- [Roland service notes](https://manuals.fdiskc.com/flat/Roland%20Juno-60%20Service%20Notes%20%28%20HI-RES%20%29.pdf), CPU schematic and adjustment procedures: components, compensation and post-VCA TP4 targets.
- [IR3109 circuit analysis](https://electricdruid.net/roland-filter-designs-with-the-ir3109-or-as3109/): independent compensation/topology interpretation.
- [AS3109](https://www.alfatriode.lv/eng/sc/AS3109.pdf) and [AS662D](https://www.alfatriode.lv/eng/sc/AS662D.pdf): replacement-device characteristics, not vintage-unit measurements.
- [Bogason/Werner, DAFx-17](https://www.dafx.de/paper-archive/2017/papers/DAFx17_paper_89.pdf), section 2.1: OTA differential-pair law.
- [OTA analysis](https://www.openmusiclabs.com/files/otadist.pdf): distortion, offsets and current/noise tradeoffs.
- [Zavalishin, topology-preserving transforms](https://www.native-instruments.de/fileadmin/redaktion_upload/pdf/KeepTopology.pdf): implicit digital feedback method.
