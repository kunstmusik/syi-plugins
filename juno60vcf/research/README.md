# Juno-60 VCF research

Circuit derivations, software measurements and hardware comparisons supporting
[juno60vcf](../README.md). The native opcode implements the filter; envelope,
LFO, keyboard, PWM and VCA mappings belong to its caller.

## Research notes

| Topic | Document |
| --- | --- |
| Circuit model, nonlinear solve, startup and noise | [Filter design](FILTER_RESEARCH.md) |
| Envelope-to-frequency conversion, cutoff bounds and drum comparisons | [VCF controls](JUNO_VCF_CONTROL_RESEARCH.md) |
| Pulse/oscillation scale, HPF, source levels and output gain | [Level calibration](JUNO_LEVEL_RESEARCH.md) |
| Raw ENV, VCA/Gate conditioning and SRC alignment | [Envelopes](JUNO_ENVELOPE_AUDIT.md) |
| Measured cutoff/resonance and depth-curve alternatives | [Depth calibration](JUNO_DEPTH_CURVE_RESEARCH.md) |
| Measured rate, depth, Auto delay and Manual behavior | [LFO](JUNO_LFO_RESEARCH.md) |
| Loaded controls, pulse polarity and saw/pulse phase | [PWM](JUNO_PWM_RESEARCH.md) |
| Reference voice's parameter ranges and calibration limits | [Control inventory](JUNO_PARAMETER_MAPPING_AUDIT.md) |
| Factory controls, stored bytes and preset validation | [Presets](JUNO_PATCH_AUDIT.md) |
| Whole-voice cost, VCA equivalence and chorus tradeoffs | [Performance](JUNO_PERFORMANCE_AUDIT.md) |
| Alternative filter behavior and excitation | [Resonance comparison](RESONANCE_REVIEW.md) |

## Evidence and fixtures

[experiments/](experiments/) contains the analysis/check scripts, capture
manifests and compact hardware-derived summaries. The factory control table and
decoded cassette bytes are retained as reference data. Generated software
reports, dense CSV traces and plots are not stored in the source tree.

Saved hardware summaries and performance baselines describe their recorded
configuration and source hashes; they are not measurements of the latest build.
Capture dates, hashes, estimator assumptions and pinned URLs are research
provenance. Historical software comparisons are summarized in the notes;
recreating an old run exactly may require its original code and binary.

[fixtures/](fixtures/README.md) contains a reference voice/preset definition,
full standalone UDO and narrowly scoped comparison baselines. It contains no
composition, mixer session or second native plugin implementation. The active
native source, example and tests live in the parent plugin directory.

Source recordings are supplied separately using the filenames, URLs and hashes
in the capture manifests. They are not redistributed here. Generated audition
audio, candidate render CSDs, compiler dumps and machine-local installation
records are not part of the research evidence kept in this tree.

## Run the checks

Build the plugin from the repository root:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure
python3 juno60vcf/research/experiments/check_juno60_filter.py
python3 juno60vcf/research/experiments/check_juno60_presets.py
python3 juno60vcf/research/experiments/check_juno60_envelopes.py
python3 juno60vcf/research/experiments/check_juno60_voice.py
```

Scripts locate inputs relative to their own files and use the root build's
`juno60vcf` module, with the platform's `.dylib`, `.so` or `.dll` extension.
For another build directory or a multi-configuration generator, set
`JUNO60VCF_PLUGIN` to the full module path. Scripts with `--plugin` also accept
that option. No installed plugin or adjacent checkout is required.

New measurements, traces, reports, plots and renders default to the ignored
`build/research-results/` directory. Compact input evidence remains in
`experiments/`. Scripts with
`--output` or `--csv` can select another destination. For example:

```sh
python3 juno60vcf/research/experiments/measure_juno60vcf.py
python3 juno60vcf/research/experiments/compare_juno60_slider_curves.py
python3 juno60vcf/research/experiments/measure_juno60_lfo.py captures/lfo
python3 juno60vcf/research/experiments/research_juno60_depth_curves.py captures/filter captures/lfo
```

Csound 7 and a matching SDK are required. Basic native/UDO checks use Python's
standard library. The analysis and full-voice scripts additionally use
NumPy/SciPy; response plots use Matplotlib, and public-recording analysis uses
ffmpeg. External-capture scripts validate their inputs against the manifests.
Software parity, finite output and preset checks establish implementation
behavior; hardware calibration remains limited by the captures and assumptions
specified in each note.

The slider-curve comparison regenerates its scalar mapping input from
`voice.blue` before comparing against the retained hardware summaries. It does
not require a checked-in generated mapping CSV. Raw-capture analyses still
require the source recordings listed in their manifests.
