# Research fixtures

- [voice.blue](voice.blue): reference synth/control/preset definitions in Blue's
  XML format. Only sample rate, block size and six instrument definitions are
  retained. Composition, mixer, score, live state and project UI/session data
  are omitted. The research scripts extract and render individual blocks.
- [Juno60Filter.csd](Juno60Filter.csd): full standalone UDO with factory examples
  and measurement taps. The active native parity tests also use the smaller
  [reference UDO](../../tests/reference/juno60_filter.udo).
- [linear_env_depth.csd](linear_env_depth.csd): explicit linear-depth FactoryPatch
  baseline for comparing the transistor-current depth correction.
- [envelope_baseline.json](envelope_baseline.json): pre-correction voice/settings
  needed by envelope audit and before/after timing probes.
- [attack_baseline.json](attack_baseline.json): pre-Attack-correction voice and
  organ settings used by hardware ENV-to-PWM analysis.

These inputs preserve specific comparison contracts, not duplicate native
implementations. Saved measurement hashes identify the source snapshots used
for those measurements; extracting the XML fixture changes its container hash.
New runs record the fixture's actual hash. Numerical measurements and recording
hashes are retained without claiming that an old source hash matches this
smaller fixture byte for byte.
