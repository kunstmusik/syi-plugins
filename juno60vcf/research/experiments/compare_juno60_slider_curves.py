#!/usr/bin/env python3
"""Compare existing slider laws with saved hardware measurements; no DSP edits.

Run: python3 experiments/compare_juno60_slider_curves.py
VCF measurements are conditional estimates, not verified production anchors.
"""
from research_paths import RESULTS
import csv
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from scipy.optimize import brentq

HERE = Path(__file__).resolve().parent


def current(voltage):
    if voltage <= 0:
        return 0.
    return brentq(lambda i: 18000*i + .02569257912108585 *
                  np.log1p(i/2.3290119196933e-14) - voltage,
                  0, voltage/18000, xtol=1e-17)


def main():
    measurements = json.loads((HERE/'juno60_depth_curves/results.json').read_text())
    dco = json.loads((HERE/'juno60_lfo/results.json').read_text())['measurements']
    # Measure the reference fixture instead of keeping generated mappings in Git.
    subprocess.run([sys.executable, str(HERE/'audit_juno60_parameter_mappings.py')],
                   check=True, stdout=subprocess.DEVNULL)
    with (RESULTS/'juno60_parameter_mapping.csv').open() as f:
        mapped = {float(r['panel']): r for r in csv.DictReader(f)}
    panels = [2.5, 5., 7.5]
    p = np.array(panels)/10
    loaded = p/(1+(50/47)*p*(1-p))
    curves = {
        'linear': p,
        'loaded_pot': loaded,
        'dco_soft_knee': np.array([float(mapped[x]['pitch_cents']) /
                                  float(mapped[10.]['pitch_cents']) for x in panels]),
        'env_transistor': np.array([float(mapped[x]['env_octaves']) /
                                   float(mapped[10.]['env_octaves']) for x in panels]),
        'loaded_env_transistor': np.array([current(5*x)/current(5) for x in loaded]),
        'adsr_cubic': p**3,
        # Remove the LEVEL curve's nonzero floor before comparing depth shapes.
        'level_exponential_zero_normalized': (10**(1.2*p)-1)/(10**1.2-1),
    }
    for panel in panels:
        assert abs(float(mapped[panel]['env_octaves'])/12 -
                   current(panel/2)/current(5)) < 1e-8
    dco_half = next(x['half_range_cents'] for x in dco
                    if x['file'].endswith('DCOmod 5.wav'))
    dco_full = next(x['half_range_cents'] for x in dco
                    if x['file'].endswith('DCOmod 10.wav'))
    vcf_entries = sorted((x for x in measurements['vcf_lfo']
                          if x['freq_panel'] == 5 and x['panel'] in panels),
                         key=lambda x: x['panel'])
    assert [x['panel'] for x in vcf_entries] == panels
    vcf = np.array([np.mean([x['amplitude_fit']['half_range_octaves'],
                            x['ratio_fit']['half_range_octaves']]) for x in vcf_entries])
    output = dict(panels=panels, dco_measured_cents_at_5=dco_half,
                  dco_measured_cents_at_10=dco_full,
                  vcf_estimated_octaves=vcf.tolist(), vcf_endpoint_candidate_octaves=3.3,
                  note='Equal estimator averages are comparison targets, not confidence bounds.',
                  curves={})
    for name, values in curves.items():
        assert np.isfinite(values).all() and np.all(np.diff(values) > 0)
        best_scale = float(values@vcf/(values@values))
        output['curves'][name] = dict(
            normalized_depths=values.tolist(),
            dco_predicted_cents_at_5=float(dco_full*values[1]),
            dco_midpoint_error_cents=float(dco_full*values[1]-dco_half),
            vcf_predicted_octaves=(3.3*values).tolist(),
            vcf_rmse_octaves=float(np.sqrt(np.mean((3.3*values-vcf)**2))),
            vcf_unconstrained_best_full_depth_octaves=best_scale,
            vcf_unconstrained_rmse_octaves=float(np.sqrt(np.mean((best_scale*values-vcf)**2))))
    # Compare timing curves separately; seconds and depth are different quantities.
    output['lfo_delay_cubic'] = {}
    for field in ['delay_seconds', 'fade_seconds']:
        records = {float(x['file'].split('Delay ')[1].split('.wav')[0]): x[field]
                   for x in dco if x['file'].startswith('LFO/Delay/')}
        output['lfo_delay_cubic'][field] = dict(
            measured=[records[x] for x in panels],
            predicted=[records[10.]*x**3 for x in p])
    dest = RESULTS/'juno60_depth_curves/slider_comparison.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(output, indent=2, allow_nan=False)+'\n')
    print(f'Wrote {dest}')
    for name, result in output['curves'].items():
        print(f"{name}: DCO midpoint error {result['dco_midpoint_error_cents']:+.2f} cents; "
              f"VCF RMS {result['vcf_rmse_octaves']:.3f} octave; "
              f"unconstrained maximum {result['vcf_unconstrained_best_full_depth_octaves']:.3f} octaves")


if __name__ == '__main__':
    main()
