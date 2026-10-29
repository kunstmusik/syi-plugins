# LFO rate, depth, waveform and trigger timing

## Hardware-derived reference

Isolated hardware recordings support the following anchors. Panel positions
are approximate physical settings on one unit, not precision voltage readings.

| Panel | Rate, Hz | DCO half-range, cents | Auto hold, s | Auto fade, s |
| --- | ---: | ---: | ---: | ---: |
| 0 | .3 nominal | off | 0 documented | 0 documented |
| 2.5 | .841 | not captured | .061 | .047 |
| 5 | 3.415 | 94.4 | .406 | .213 |
| 7.5 | 11.644 | not captured | 1.038 | .557 |
| 10 | 22.107 | 223.2 | 2.505 | 1.347 |

The rate-0 recording contains no full cycle, so it does not establish .3 Hz.
Rate-2.5 has only one complete interval. Rate uses logarithmic interpolation;
hold/fade use linear interpolation. Linear fade fits the measured Auto extrema
with roughly .4–1.2% normalized RMS error. The maximum hold differs from the
service target of approximately 2 s and is explicitly a fit to the captured unit.

Fundamental-band analytic phase estimates rate; rising zero-crossing periods
independently estimate depth and onset. Note edges and silence are excluded.
Measured depth is half the cents excursion and is invariant to a constant tuning
offset. The reference's centered cents model omits some observed asymmetry.
[Results](experiments/juno60_lfo/results.json) retain the compact fitting details.
The analysis script regenerates measurement CSVs and waveform traces from the
source recordings into `build/research-results/`.

## Reference implementation

DCO/VCF share rounded modulation `tanh(2*x)/tanh(2)` for triangle x in [-1,1].
PWM receives the raw free-running triangle and is independent of vibrato delay.
The rounded shape includes the DCO branch/clock converter; a VCF-specific
waveform measurement remains necessary.

DCO depth uses a soft current knee around .6 V with .06 V width and a
225-cent maximum. The reference Brass setting at depth 1.5 is approximately
±7.91 cents at 3.415 Hz. Auto delay 6.5 gives .785 s hold plus .419 s fade,
so short notes precede vibrato and sustained notes develop it gradually.
The low-depth value is a circuit-based estimate, not a hardware Brass fit.
See [depth calibration](JUNO_DEPTH_CURVE_RESEARCH.md).

Auto timing starts with the first held key and is shared across legato notes.
Released voices do not restart the held-key counter. Manual starts fading from
a trigger press, stops on release and restarts on another press. Joining notes
share that press's gain. Voice and output stages use the same explicit synth
channel identifier; generated voice/output instrument numbers may differ.

Manual uses the measured Auto hold-duration curve as its fade duration. That
equivalence lacks an isolated hardware capture. Auto gain reset on key-up with
sounding release tails is also implementation behavior awaiting measurement.

## Reproduction and sources

[check_juno60_lfo.py](experiments/check_juno60_lfo.py) exercises all reference
channel pairs, independent voice/output IDs, hold/fade/legato, Manual late
press/repress, zero delay, PWM independence and actual DCO depth.
[measure_juno60_lfo.py](experiments/measure_juno60_lfo.py) validates supplied
recordings against the [capture manifest](experiments/juno60_lfo/captures.json).

- [Hardware LFO captures](https://github.com/pendragon-andyh/Juno60/tree/beab8655781db7dadf2bf9fa6e3d4b6514de3132/LFO) and [test plan](https://github.com/pendragon-andyh/Juno60/blob/beab8655781db7dadf2bf9fa6e3d4b6514de3132/TestPlan/Juno60_ToneTestPlan.xlsx).
- [Roland service notes](https://medias.audiofanzine.com/files/roland-juno-60-service-notes-472222.pdf), rate maximum, TP19 and gradual modulation return.
- [Owner's manual](https://cdn.roland.com/assets/media/pdf/JUNO-60_OM.pdf), Auto first-key and Manual trigger semantics.

Polyphonic/chorused factory performances are useful listening references but
cannot independently calibrate LFO rate/depth or Manual timing.
