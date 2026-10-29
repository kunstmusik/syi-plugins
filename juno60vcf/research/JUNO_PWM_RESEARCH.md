# PWM control and oscillator phase

## Loaded slider and source selection

With normalized panel p, the 50kB slider and 47k wiper load give
`u=p/(1+(50/47)*p*(1-p))`. The reference Manual endpoint calibration is 50% duty
at zero and 95% at full scale. The service procedure takes precedence over an
illustrative 97% label elsewhere in the notes.

PWM LFO uses raw TP17 before the vibrato delay/trigger path. Its triangle is
nominally 20 Vp-p. PWM must continue with vibrato untriggered or delayed.
For ideal rails and high-impedance OTA input, using resistor values in kOhms:

```text
Rl = 82 + .470
Vman = (15/39)/(1/39+1/15+1/Rl) = 3.68288021 V
G = 1/82+1/120+1/33+1/Rl
Vlfo = (10*x/82+15/120)/G
Vlfo/Vman = .539110334 + .525961301*x
D = clamp(.5+.45*u*source, 0, 1)
source: Manual=1; LFO=Vlfo/Vman; ENV=raw normalized voice envelope
```

The circuit estimate includes the R115/R117 load. It omits switch resistance,
OTA input nonlinearity, bias, device tolerances and control settling.
At full depth the estimated LFO duty spans 50.59–97.93%; at Strings 2's panel 6,
u=.4779661 and duty spans 50.283–72.908% around 61.595%.

## Pulse polarity and saw phase

The hardware comparator produces a pulse high late in the falling-saw cycle,
with its moving edge before the fixed saw-reset edge. For Csound's vco2,
use `-vco2(1, frequency, 2, 1-D)`. Remove mean `2*D-1` afterward as a reduced
AC-coupling approximation. The original equal-level direct pulse/saw addition
put their fundamentals in phase, yielding a three-times rather than one-times
saw fundamental in the 50% additive approximation.

Correcting comparator phase does not establish a complete DCO mixer transfer.
The hardware uses diode switching, source loading and C5 coupling. Analytical
mean removal omits the coupling network's time response, and nominal additive
saw/pulse/sub ratios remain calibration assumptions.

## ENV calibration and checks

ENV PWM uses raw per-voice ENV, independent of VCF polarity and VCA ENV/Gate.
The reference assumes normalized peak 1. If the hardware ENV peak is E volts,
the resistor approximation gives peak source about `.1056563*E`; the actual
TP6 peak is not established by the inspected calibration procedure.

[check_juno60_pwm.py](experiments/check_juno60_pwm.py) verifies Manual endpoints,
loaded midpoint, bounded ENV, component-derived LFO conversion, raw routing,
Strings 2's range and saw/pulse phase. Its generated
`build/research-results/juno60_pwm.csv` records software results.

For hardware comparison, keep output gain fixed, filter open, RES/HPF 0 and
chorus off. Record Manual pulse at 0/5/6/10, slow LFO PWM at 6/10, saw alone,
saw+pulse and ENV PWM at several sustains. Repeat with vibrato trigger off and
delay maximum. Do not normalize takes independently.

## Sources

- [Roland service notes](https://medias.audiofanzine.com/files/roland-juno-60-service-notes-472222.pdf), Panel A/CPU/PWM circuits and adjustment §9.
- [Owner's manual](https://cdn.roland.com/assets/media/pdf/JUNO-60_OM.pdf), Manual/LFO/ENV operation.
