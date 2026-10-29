# Drum pitch and tape measurements

The compact [fit results](results.json) describe the linear-depth baseline in
[linear_env_depth.csd](../../fixtures/linear_env_depth.csd).
Labels containing `current` in saved measurement rows denote that baseline,
not the active plugin or a claim of up-to-date caller calibration.

Hardware initial slope was −8.881 octaves/s versus −11.628 for the baseline.
A 105 ms model hold explains part of the later bend, without establishing the
unknown hardware key-off. Shallower-depth and slower-decay candidates both fit
closely when a constant tuning offset is allowed. Their parameters are retained
in JSON; generated audition renders can be reproduced rather than stored.

The [bank-A byte table](factory_bank_A_bytes.csv) and [tape metadata](factory_tape.json)
record an independent decode with all 64 checksums valid. ADC/DAC bytes are not
linear physical slider positions, and switch interpretation remains incomplete.

Run `experiments/measure_juno60_drum_pitch.py captures/public captures/harman`
from the research directory with the inputs identified by the capture manifests.
Pitch traces and metric tables are generated under `build/research-results/`.
See [VCF controls](../../JUNO_VCF_CONTROL_RESEARCH.md) for estimator assumptions,
source references and the subsequent driver correction.
