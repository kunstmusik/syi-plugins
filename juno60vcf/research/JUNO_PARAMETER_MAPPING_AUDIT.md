# Reference voice control inventory

This inventory describes the executable [voice fixture](fixtures/voice.blue),
including its output stage. The native filter accepts the final cutoff in Hz,
resonance and drive; panel calibration is caller behavior. Numerical checks
establish connectivity and implemented mappings, not accuracy against hardware.

## Controls

`p` below means panel/10; `u(p)=p/(1+(50/47)*p*(1-p))`.
“Live” means a k-rate expression when Blue supplies a changing control value.

| Parameter | Stored range / meaning | DSP mapping and status |
|---|---|---|
| `lfo_rate` | 0–10 | Live; log interpolation through .3/.8414/3.4147/11.6442/22.1067 Hz at 0/2.5/5/7.5/10. Minimum nominal, remaining anchors measured. |
| `lfo_delay_time` | 0–10 | Live; Auto hold 0/.061/.406/1.038/2.505 s and fade 0/.047/.213/.557/1.347 s. Linear interpolation. Manual uses hold curve as fade. |
| `lfo_trigger_mode` | 0 Auto, 1 Manual | Live; shared first-held-key timing versus trigger-button timing. Threshold .5. |
| `lfo_trig` | 0 released, 1 pressed | Live Manual gate; ignored in Auto. |
| `dco_lfo` | 0–10 | Live; soft-knee cents mapping, exact zero, approximately ±225 cents max. Finding 1. |
| `dco_pwm` | 0–10 | Live; .45*u(p) duty excursion times selected source, added to .5. |
| `dco_pwm_source` | 0 LFO, 1 Manual, 2 ENV | Live; .539110334+.525961301*raw triangle / 1 / raw ENV. Correct labels and branches. |
| `dco_sub` | 0–10 | Live; u(p) amplitude at half fundamental frequency. |
| `dco_noise` | 0–10 | Live; u(p) times uniform white noise in [−1,1]. |
| `dco_saw_enabled` | 0/1 | Live exact-1 switch; unit-amplitude falling saw. |
| `dco_pulse_enabled` | 0/1 | Live exact-1 switch; complement/invert pulse to align with saw, remove duty mean. |
| `dco_sub_enabled` | 0/1 | Live exact-1 switch; square at one octave down. |
| `dco_noise_enabled` | 0/1 | Live exact-1 switch; software source-enable control. |
| `vcf_freq` | 0–10 | Live; 7.8 Hz * 2^(1.66667*panel + other contributions), then caller/native guards. Finding 3. |
| `vcf_res` | 0–10 | Live; panel/10, native clamp 0–1, K=4.2*res. Finding 3. |
| `vcf_env` | 0–10 | Live, cached solve; 0–5 V through reduced TR36 current model, normalized to 12 octaves. At 5: 5.25066 octaves. |
| `vcf_lfo` | 0–10 | Live, cached; DCO soft-knee shape with separate ±3.46-octave maximum, times shared modulation/gain. At 2.5/5/7.5: .511/1.494/2.477 octaves. Provisional audition trial. |
| `vcf_kybd` | 0–10 | Live; p*(octcps(note frequency)−8). Zero contribution at MIDI 60, unity octave tracking at 10. |
| `vcf_invert` | 0 Normal, 1 Inverted | Live; reverses ENV contribution only, not LFO or key tracking. |
| `env_attack` | 0–10 | Init; .001+2.999*p^3 seconds, segment curvature −1. |
| `env_decay` | 0–10 | Init; .002+11.998*p^3 seconds, curvature −4.2. |
| `env_sustain` | 0–10 | Init; p normalized ENV voltage. |
| `env_release` | 0–10 | Init; .002+11.998*p^3 seconds, curvature −4.2. |
| `vca_mode` | 0 ENV, 1 Gate | Init; ENV through reduced C9 network or asymmetric Gate. Raw ENV still drives VCF/PWM in Gate mode. |
| `vca_level_adjust` | −5…+5 | Live global gain; 10^((panel−5)*2.4/20), before chorus. |
| `hpf_mode` | 0–3 | Live integer; bypass / 234.614 / 516.150 / 1098.192 Hz, first-order after voice sum. Circuit estimates. |
| `chorus_mode` | 0–4 | Live; off / I (.5 Hz) / II (.8 Hz) / combined Juno-60 (1 Hz) / combined Juno-6 (8 Hz). Separate chorus modulation. |

VCF ENV's linear input-voltage assumption is **not** the same omission as DCO
LFO: VR1's 4.7k resistor is in series with the ADC input, not a 47k load to
ground. Its reduced transistor solver is numerically checked, but nominal
transistor/trim parameters and its 12-octave full scale remain assumptions.
At the service ENV-max condition it requests 31.949 kHz rather than ~30 kHz.

The raw envelope branches to VCF/PWM before VCA conditioning. The `filter2`
replacement preserves that conditioning and does not change modulation depth
or oscillator rate. HPF and patch LEVEL are correctly common post-voice stages.
There is no new native-opcode requirement arising from these mapping findings.

## Calibration priorities

DCO LFO depth has only midpoint/full-scale hardware anchors. Its soft knee
omits the documented pot loading; inserting loading without recalibrating the
current driver and clock converter spoils those anchors. FREQ, VCF depth and
resonance likewise need coherent control-voltage calibration, rather than
independently guessed slider curves. The VCF LFO soft-knee mapping is a
provisional fit; see [depth research](JUNO_DEPTH_CURVE_RESEARCH.md).

ADSR and VCA mode are sampled at note start. Live slider controls remain
k-rate, and expensive depth conversions are cached until their input changes.
Score p4 is MIDI note number; p5 is dBFS gain, not MIDI velocity.

The [mapping script](experiments/audit_juno60_parameter_mappings.py) renders
101 panel values and checks finite, monotonic scalar outputs. The
[preset checks](experiments/check_juno60_presets.py) validate stored values and
labels. The generated `build/research-results/juno60_parameter_mapping.csv`
records the reference outputs. Raw cassette ADC/DAC bytes are control voltages,
not linear slider percentages; see [preset research](JUNO_PATCH_AUDIT.md).
