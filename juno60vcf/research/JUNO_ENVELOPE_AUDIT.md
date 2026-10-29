# Envelope, Gate and filter/VCA alignment

## Shared raw ENV and separate VCA conditioning

The reference voice routes one raw envelope to VCF and PWM. VCA mode selects
that envelope through its own conditioning network or an asymmetric Gate.
VCA filtering must not alter the raw envelope used for filter modulation.

The reduced ENV branch is
`12/49*ENV + 37/49*lowpass(ENV, tau=10.78 ms)`. With
`p=exp(-1/(sr*tau))`, its exact discrete transfer is:

```text
H(z) = [1-(37/49)*p-(12/49)*p*z^-1] / [1-p*z^-1]
```

A plain lowpass loses the direct feedthrough. A first-order `filter2` implements
this network; see [performance equivalence](JUNO_PERFORMANCE_AUDIT.md).
Gate rise/fall time constants are .982/4.840 ms from an ideal RC approximation,
truncated at 14 time constants for a residual below 1 ppm. TR6 loading/offset
and the complete retrigger/persistent-voice behavior remain unmodeled.

## Converter delay

The native medium-sinc 2x/4x path measured 94 caller samples of impulse delay
at 44.1/48/96 kHz and ksmps 1/32/64/128. Delay the external conditioned VCA by
94/sr and retain the voice for the control tail plus delay. At 1x there is no
converter delay and the VCA delay must be removed. The UDO has the same settled
delay, but converter startup can vary with block size.

[Envelope checks](experiments/check_juno60_envelopes.py) and the
[baseline audit](experiments/audit_juno60_envelopes.py) with `--before` separate artificial
minimum-Attack jumps, incompatible envelopes and converter misalignment from
remaining differences in hardware attack character. A click alone is not proof
of an implementation defect: the factory Organ 1 reference has a pronounced
key transient.

Their generated timing tables and dense traces go under `build/research-results/`.

## Measured Attack and provisional duration laws

Independent hardware ENV-to-PWM captures support Attack curvature near −1:
three fits gave −.959/−1.104/−1.084. The reference uses −1 for Attack while
Decay/Release retain provisional −4.2. The measured
[Attack results](experiments/juno60_attack_curve/) include source hashes,
traces, fitting methods and onset-estimator limitations.

For normalized panel p, reference durations are:

```text
Attack = .001 + 2.999*p^3 seconds
Decay/Release = .002 + 11.998*p^3 seconds
Sustain = p, a generator-voltage fraction
```

| Panel | Attack | Decay/release |
| --- | ---: | ---: |
| 0 | 1 ms | 2 ms |
| 1 | 4.00 ms | 14.00 ms |
| 5 | 375.875 ms | 1.50175 s |
| 10 | 3 s | 12 s |

Endpoints do not validate intermediate times. ADR and VCA mode are sampled at
note initialization in the fixture; later control movement affects subsequent
notes. This is an intentional execution contract. Absolute ENV gain, sustain
interaction, D/R curvature and complete voice/retrigger dynamics remain open.

## Reproduction and sources

[Envelope checks](experiments/check_juno60_envelopes.py) cover all six reference
voices, minimum-Attack continuity, RC/Gate timing, tails and converter alignment.
[Attack analysis](experiments/measure_juno60_attack_curve.py) needs the captures
identified in its [manifest](experiments/juno60_attack_curve/captures.json).
[Baseline fixtures](fixtures/README.md) preserve the pre-correction envelope
expressions for controlled comparisons.

- [Roland service notes](https://medias.audiofanzine.com/files/roland-juno-60-service-notes-472222.pdf), ENV/VCA circuitry and timing targets.
- [Owner's manual](https://cdn.roland.com/assets/media/pdf/JUNO-60_OM.pdf), envelope and Gate operation.
- [Andy Harman hardware study](https://github.com/pendragon-andyh/Juno60), isolated Attack/PWM recordings and test plan.
- [IR3R01 analysis](https://amsynths.co.uk/2019/05/09/roland-ir3r01-clone/), useful circuit context rather than a complete numeric timing dataset.
