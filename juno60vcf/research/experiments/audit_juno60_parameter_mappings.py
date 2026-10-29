#!/usr/bin/env python3
"""Record actual instrument-6 scalar mappings; this does not validate hardware accuracy."""
from research_paths import RESULTS
from pathlib import Path
import xml.etree.ElementTree as E
import re, subprocess, os, csv, hashlib, json, tempfile
import numpy as np
from scipy.io import wavfile
root=Path(__file__).resolve().parents[1]
src=root/'fixtures/voice.blue'; data=src.read_bytes(); inst=E.fromstring(data).find(".//instrumentAssignment[@arrangementId='6']/instrument")
voice=inst.findtext('instrumentText'); post=inst.findtext('alwaysOnInstrumentText')
block=voice.split('// SLIDER VALUES',1)[1].split('tigoto',1)[0]
block=re.sub(r'<[a-z_]+>','p4',block)
fields=['pitch_cents','sub_gain','noise_gain','resonance','env_octaves','lfo_octaves','attack_seconds','decay_seconds','sustain','release_seconds']
vars=['kPitchCents','kSubLevel','kNoiseLevel','kResonance','kEnvModOct','kLfoModOct','iEnvA','iEnvD','iEnvS','iEnvR']
csd='<CsoundSynthesizer>\n<CsOptions>\n-d -m0\n</CsOptions>\n<CsInstruments>\nsr=48000\nksmps=32\nnchnls=10\n0dbfs=1\ninstr 1\n'+block+'\nout('+','.join('a('+v+')' for v in vars)+')\nendin\n</CsInstruments>\n<CsScore>\n'+'\n'.join(f'i 1 {n*.02:.4f} .02 {n/10}' for n in range(101))+'\ne\n</CsScore>\n</CsoundSynthesizer>'
with tempfile.TemporaryDirectory(prefix='juno-mappings-') as temp:
 directory=Path(temp)
 csd_path=directory/'mappings.csd'; wav_path=directory/'mappings.wav'
 csd_path.write_text(csd)
 env=dict(os.environ,CS_USER_PLUGINDIR=temp,OPCODE7DIR=temp,OPCODE7DIR64=temp)
 p=subprocess.run(['csound','-W','--format=double','-o',str(wav_path),str(csd_path)],env=env,capture_output=True,text=True,timeout=30)
 assert p.returncode==0,p.stderr
 sr,a=wavfile.read(wav_path)
 values=a[(np.arange(101)*.02*sr+.01*sr).astype(int)]
assert np.isfinite(values).all(); assert (np.diff(values,axis=0)>-1e-9).all()
rows=[dict(panel=n/10,**dict(zip(fields,map(float,row)) )) for n,row in enumerate(values)]
out=RESULTS/'juno60_parameter_mapping.csv'
with out.open('w') as f:
 w=csv.DictWriter(f,rows[0]);w.writeheader();w.writerows(rows)
meta=dict(project_sha256=hashlib.sha256(data).hexdigest(),method='Actual instrument-6 scalar mapping block rendered with all slider inputs swept together, 0..10 by 0.1; sampled 10 ms into each fresh note. No filter or hardware audio.',sr=sr,ksmps=32,rows=len(rows),finite=True,monotonic=True)
(RESULTS/'juno60_parameter_mapping.json').write_text(json.dumps(meta,indent=2)+'\n')
assert src.read_bytes()==data
print(meta)
for n in [0,15,50,100]:print(rows[n])
