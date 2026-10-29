# ENV depth-driver measurements

[Results](results.json) summarize the comparison of the
reference voice's nominal TR36 PNP depth law with an independently bracketed
root solve. At panel 4 the depth is 3.90985 octaves, versus linear depth 4.8;
the 12-octave full scale remains provisional.

The drum comparison uses a 105 ms hold inferred from the recording's later
slope bend, pitch alignment and first-100ms RMS matching. Source hashes,
nominal device/trim assumptions, sensitivity and fit limitations are in the
JSON. A small onset-window pitch error does not validate the full hardware model.

The [linear-depth fixture](../../fixtures/linear_env_depth.csd) supplies the
baseline for reproducible comparisons. Run
`experiments/check_juno60_env_depth.py captures/public captures/harman` from
the research directory with matching raw captures. New plots/audio/CSDs are
written under the ignored root build directory, along with the generated control
sweep CSV.

See [VCF control research](../../JUNO_VCF_CONTROL_RESEARCH.md) for circuit
references, derivation and remaining gain/baseline uncertainty.
