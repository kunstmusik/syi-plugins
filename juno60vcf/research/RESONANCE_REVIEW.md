# Resonance and alternative-filter comparison

The Juno-60 circuit is a four-stage OTA cascade with a BA662 resonance limiter,
not a coupled diode ladder. Alternative Csound filters are useful diagnostics,
but topology, amplitude regulation and startup must be compared separately.

| Opcode | Relevant behavior | Consequence |
| --- | --- | --- |
| zdfladder | Four linear TPT stages; Q clamps .5–25, feedback 0–4 | Marginal maximum resonance, no autonomous amplitude regulation |
| diodeladder | Coupled stages; optional input saturation precedes feedback subtraction | Different tuning; input tanh does not regulate a source-free ring |
| moogladder | Nonlinear stages within the loop, two internal substeps | Bounded-oscillation candidate with Moog rather than Juno nonlinearities |

All initialize to zero and remain silent without excitation. Sustained forcing
or noise accumulation can grow output even when a fixed-cutoff pole is marginal;
that is not a measured exponential instability. A burst-then-silence probe is
more informative than a continuously forced resonance test.

The isolated [comparison script](experiments/filter_compare.py) uses a seeded
20 ms noise burst, then silence. Early/late windows are .2–.4 and 2.8–3 s at
44.1 kHz, ksmps 32 and 0dbfs 1. Resonance fraction maps to Q=.5+24.5*r for ZDF,
17*r for diode and r for Moog. Its CSV output includes exact-zero checks, RMS and
ring frequency. Redirect stdout to a file under `build/research-results/` to
retain a generated report.

Q above 25 cannot raise zdfladder feedback above 4. Its `1+K*G^4` solve
denominator is not passband compensation; the uncompensated linear cascade has
DC gain 1/(1+K). An output tanh cannot stabilize divergent internal states.
The native model instead includes the schematic's input-to-feedback OTA path
and solves its nonlinearity inside the loop; see [filter design](FILTER_RESEARCH.md).

Hardware filter cores remain powered while VCAs close. A note-local software
instance resets state and must either be excited or use an explicit startup
approximation. Native warm initialization is such an approximation; persistent
hardware voice history remains a separate modeling question.

Sources: [Roland service notes](https://medias.audiofanzine.com/files/roland-juno-60-service-notes-472222.pdf),
[SoundForce circuit reconstruction](https://sound-force.nl/vcfvca-6/),
[Cytomic circuit descriptions](https://www.cytomic.com/files/TheDrop-Manual.pdf),
and [Huovilainen's nonlinear Moog model](https://www.dafx.de/paper-archive/2004/P_061.PDF).
These sources support topology/method distinctions, not interchangeability
with a calibrated original Juno-60.
