#!/usr/bin/env python3
"""Check the actual ENV driver against a bracketed transistor solve; audition drum78.

python3 experiments/check_juno60_env_depth.py captures/public captures/harman
Uses existing Csound/NumPy/SciPy. Full-range gain, nominal transistor parameters
and hardware audio alignment remain calibration assumptions, recorded below.
"""
from research_paths import RESULTS
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from scipy.io import wavfile
from scipy.optimize import brentq

from check_juno60_patches import read_taps
from check_juno60_startup import ORCHESTRA, PLUGIN, render
from measure_juno60_drum_pitch import onset, trajectory, metrics

PROJECT = Path(__file__).resolve().parents[1]
DEST = RESULTS / 'juno60_env_depth'
VT = .02569257912108585


def driver_current(voltage, reference_vbe=.57, resistance=18000, beta=200):
    """Positive emitter current; Shockley and emitter-resistor equations."""
    if voltage <= 0:
        return 0.
    saturation = .0001/np.expm1(reference_vbe/VT)*(1+1/beta)
    return brentq(lambda i: resistance*i+VT*np.log1p(i/saturation)-voltage,
                  0, voltage/resistance, xtol=1e-17)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('public_directory',type=Path)
    parser.add_argument('harman_directory',type=Path)
    args = parser.parse_args()
    root = ET.parse(PROJECT/'fixtures/voice.blue').getroot()
    voices = root.findall('.//instrumentAssignment/instrument/instrumentText')
    blocks = ['; VCF ENV:'+voice.text.split('; VCF ENV:',1)[1].split('; VCF LFO',1)[0]
              for voice in voices]
    assert len(blocks)==6 and all(block==blocks[0] for block in blocks)
    panels = np.r_[np.arange(-1,11.01,.25),np.arange(10,-.01,-.5)]
    # Drive the same k-rate block forward and backward through its cache.
    block = blocks[0].replace('<vcf_env>','kPanel')
    controls = []
    with tempfile.TemporaryDirectory(prefix='juno60-depth-') as temporary:
        directory = Path(temporary)
        csd = f'''<CsoundSynthesizer>
<CsOptions>
-d -m0
</CsOptions>
<CsInstruments>
sr=48000
ksmps=32
nchnls=3
0dbfs=1
giPanels=ftgen(0,0,-{len(panels)},-2,{','.join(map(str,panels))})
instr Probe
kPanel=table:k(min(floor(timeinsts()*100),{len(panels)-1}),giPanels)
{block}
out(a(kEnvModOct),a(kEnvVoltage),a(kEnvJunction))
endin
</CsInstruments>
<CsScore>
i "Probe" 0 {len(panels)*.01+.01}
e
</CsScore>
</CsoundSynthesizer>
'''
        (directory/'control.csd').write_text(csd)
        environment=dict(os.environ,CS_USER_PLUGINDIR=temporary,OPCODE7DIR=temporary,OPCODE7DIR64=temporary)
        result=subprocess.run(['csound','-W','--format=double','-o',str(directory/'control.wav'),
                               str(directory/'control.csd')],env=environment,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        (depth,voltage,junction),rate=read_taps(directory/'control.wav')
        full=driver_current(5)
        for index,panel in enumerate(panels):
            sample=round((index*.01+.005)*rate)
            cv=5*np.clip(panel/10,0,1)
            expected=12*driver_current(cv)/full
            actual=depth[sample]
            assert abs(actual-expected)<1e-8,(panel,actual,expected)
            assert abs(voltage[sample]-cv)<1e-12
            controls.append(dict(panel=float(panel),control_volts=float(cv),
                                 expected_depth_octaves=float(expected),measured_depth_octaves=actual,
                                 junction_volts=junction[sample]))

        source_entry=next(x for x in json.loads((PROJECT/'experiments/juno60_public_recordings.json').read_text())['captures']
                          if x['file']=='synthmania-78-Synthesizer-Drum.mp3')
        source=args.public_directory/source_entry['file']
        assert hashlib.sha256(source.read_bytes()).hexdigest()==source_entry['sha256']
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-c:a','pcm_f32le',
                        str(directory/'hardware.wav')],check=True)
        rate,hardware=wavfile.read(directory/'hardware.wav')
        hardware=hardware[:,0].astype(float)
        hw_time,hw_pitch=trajectory(hardware,rate)
        rows=[dict(variant='hardware',**metrics(hw_time,hw_pitch))]
        start=round(onset(hardware[:round(.17*rate)],rate)*rate)
        excerpts=[hardware[start:start+round(.15*rate)]]
        before=(PROJECT/'fixtures/linear_env_depth.csd').read_text().split('<CsInstruments>',1)[1].split('</CsInstruments>',1)[0]
        candidates=[]
        for label,body in [('linear_before',before),('circuit_after',ORCHESTRA)]:
            native=body.replace(
                'aFiltered = juno60_filter(aTestInput, aCutoff, aResonance, aDrive, 1, iThermalNoise, iWarmStart)',
                'aFiltered = juno60vcf(aTestInput, aCutoff, aResonance, aDrive, 1, 4, iWarmStart)')
            def note(code,is_native):
                raw,gated,_=render(directory,code,'i "FactoryPatch" 0 3.5 78 5 0 0 .105 60',rate,32,native=is_native)
                return np.asarray(gated)
            signal=note(native,True)
            time,pitch=trajectory(signal,rate)
            unshifted=metrics(time,pitch)
            shift=np.log2(rows[0]['early_hz']/unshifted['early_hz'])
            tuned=native.replace('octcps(cpsmidinn(iNote))-8',f'octcps(cpsmidinn(iNote))-8 + {shift:.12g}')
            signal=note(tuned,True)
            time,pitch=trajectory(signal,rate)
            rows.append(dict(variant=label,**metrics(time,pitch)))
            start=round(onset(signal[:round(.17*rate)],rate)*rate)
            gain=.12/np.sqrt(np.mean(signal[start:start+round(.10*rate)]**2))
            excerpts.append(signal[start:start+round(.15*rate)].copy())
            assert np.max(abs(signal*gain))<1
            wavfile.write(DEST/f'drum_{label}.wav',rate,(signal*gain).astype(np.float32))
            (DEST/f'drum_{label}.csd').write_text((directory/'probe.csd').read_text().replace('out(aFiltered, aOut)','out(aOut, aOut)'))
            candidates.append(dict(variant=label,unshifted=unshifted,tuning_shift_octaves=float(shift),gain=float(gain)))
            if label=='circuit_after':
                # Different implementations/SRC phases; compare robust octave fall.
                udo=note(body,False)
                ut,up=trajectory(udo,rate)
                parity=metrics(ut,up)
                assert abs(parity['fall_octaves']-unshifted['fall_octaves'])<.01
        audition=[]
        for clip in excerpts:
            clip=clip.copy()
            clip*=.12/np.sqrt(np.mean(clip[:round(.10*rate)]**2))
            fade=round(.002*rate)
            clip[-fade:]*=np.linspace(1,0,fade)
            audition.extend(clip)
            audition.extend(np.zeros(round(.55*rate)))
        wavfile.write(DEST/'drum_driver_comparison.wav',rate,np.asarray(audition,dtype=np.float32))

    # Independent filter-zero estimate, conditional on common recording gain
    # and identical four-pole response. No production FREQ calibration uses it.
    static=[]
    downloads=json.loads((args.harman_directory/'filter_downloads.json').read_text())
    for name in ('Juno 60 LPF=0.wav','Juno 60 LPF=5.wav','Juno 60 LPF=7.5.wav','Juno 60 LPF=10.wav'):
        path=args.harman_directory/name
        sample_rate,raw=wavfile.read(path)
        audio=raw[:,0].astype(float)/2**31
        count,step=round(.15*sample_rate),round(.01*sample_rate)
        t=np.arange(count)/sample_rate
        weight=np.hanning(count);weight/=weight.sum()
        kernel=weight*np.exp(-2j*np.pi*54.88*t)
        amplitude=max(2*abs(np.sum(audio[i:i+count]*kernel)) for i in range(0,len(audio)-count,step))
        static.append(dict(file=name,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            source_url=next(x['url'] for x in downloads if x['file']==name),maximum_fundamental_amplitude=float(amplitude)))
    gain=static[0]['maximum_fundamental_amplitude']/static[-1]['maximum_fundamental_amplitude']
    zero=54.88/np.sqrt(gain**-.5-1)
    conditional_full=np.log2(30000/zero)
    sensitivity=[]
    for resistance in (13000,18000,23000):
        for reference_vbe in (.54,.57,.60,.63):
            ratio=driver_current(2,reference_vbe,resistance)/driver_current(5,reference_vbe,resistance)
            sensitivity.append(dict(resistance_ohms=resistance,vbe_at_100uA=reference_vbe,
                                    panel4_depth_octaves=float(12*ratio)))
    with (DEST/'control_sweep.csv').open('w',newline='') as output:
        writer=csv.DictWriter(output,controls[0].keys());writer.writeheader();writer.writerows(controls)
    result=dict(source=source_entry,nominal=dict(temperature_celsius=25,beta=200,reference_collector_current_amperes=.0001,
        reference_vbe_volts=.57,series_resistance_ohms=18000,emitter_saturation_current_amperes=2.3290119196933e-14,
        panel4_depth_octaves=float(12*driver_current(2)/driver_current(5)),full_depth_octaves=12),
        sensitivity=sensitivity,metrics=rows,udo_unshifted=parity,candidates=candidates,
        static_filter_captures=static,conditional_freq0_pole_hz=float(zero),
        conditional_depth_for_30k_endpoint_octaves=float(conditional_full),
        audition_order=['hardware','linear_before','circuit_after'],slot_seconds=.7,excerpt_seconds=.15,
        audition_gain='RMS .12 over first 100ms; pitch shifts explicit; end-only 2ms crop fade',
        hold_seconds=.105,blue_sha256=hashlib.sha256((PROJECT/'fixtures/voice.blue').read_bytes()).hexdigest(),
        csd_sha256=hashlib.sha256((PROJECT/'fixtures/Juno60Filter.csd').read_bytes()).hexdigest(),
        plugin_sha256=hashlib.sha256(PLUGIN.read_bytes()).hexdigest(),
        limits='Driver structure is from the service schematic. Vbe at 100uA is an approximate reading of the typical 2SA1015 graph; beta, gain-trim midpoint and temperature are nominal. Alternative 2SA1115 and actual trim are unknown. Full ENV gain, raw-ENV OTA transfer and FREQ baseline remain provisional. Static pole estimate assumes common gain and four equal poles. Audio note/key events are unknown; .105s hold is inferred. No drum-fit parameter is used in the production depth curve.')
    (DEST/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(nominal=result['nominal'],metrics=rows,conditional_freq0_hz=float(zero)),indent=2))
    print(f'PASS: {len(panels)} bidirectional control points, six identical Blue mappings, UDO/native drum check; {DEST}')


if __name__=='__main__':
    main()
