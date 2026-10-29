#!/usr/bin/env python3
"""Check actual Blue ENV/Gate paths and native latency; render Organ A/B clips."""
from research_paths import PLUGIN, RESULTS
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave
import xml.etree.ElementTree as ET

from check_juno60_patches import read_taps
from check_juno60_startup import ORCHESTRA, render as render_udo

PROJECT = Path(__file__).resolve().parents[1]
DEST = RESULTS / 'juno60_envelopes_corrected'
TAU_ON = .22e-6 / (1/5600 + 1/22000)
TAU_OFF = .22e-6 * 22000


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    source = (PROJECT/'fixtures/voice.blue').read_bytes()
    root = ET.fromstring(source)
    instruments = root.findall('.//instrumentAssignment/instrument')
    baseline = json.loads((PROJECT/'fixtures/envelope_baseline.json').read_text())
    settings = baseline['settings']
    rows, latency, controls, audition, order = [], [], [], [], []
    with tempfile.TemporaryDirectory(prefix='juno60-envelopes-') as temporary:
        directory = Path(temporary)
        env = dict(os.environ, CS_USER_PLUGINDIR=temporary,
                   OPCODE7DIR=temporary, OPCODE7DIR64=temporary)

        def render(body, values, rate=48000, block=32):
            hold = math.ceil(.3*rate/block)*block/rate
            body = body.replace('<INSTR_ID>', '6')
            for key, value in values.items():
                body = body.replace(f'<{key}>', str(value))
            assert not re.findall(r'<[A-Za-z_]\w*>', body)
            csd, wav = directory/'probe.csd', directory/'probe.wav'
            csd.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0 --sample-accurate
</CsOptions>
<CsInstruments>
sr={rate}
ksmps={block}
nchnls=3
0dbfs=1
seed 1234
instr Lfo
kLfo = lfo:k(1, .3*pow(20/.3, {values['lfo_rate']}/10), 1)
chnset(kLfo, "jno60_lfo_6")
endin
instr Voice
{body}
endin
</CsInstruments>
<CsScore>
i "Lfo" 0 {hold+1}
i "Voice" 0 {hold} 60 0
e
</CsScore>
</CsoundSynthesizer>
''')
            result = subprocess.run(['csound', f'--opcode-lib={PLUGIN}',
                '-W', '--format=double', '-o', str(wav), str(csd)],
                env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            taps, actual = read_taps(wav)
            assert actual == rate
            return taps, round(hold*rate)

        for rate, block in ((44100,64),(48000,32),(96000,64),(48000,1),(48000,128)):
            for factor in (1,2,4):
                body = f'aIn=mpulse:a(1,0,.01)\naOut=juno60vcf(aIn,.49*sr,0,1,1,{factor},0)\nout(aIn,aOut,a(0))'
                (inp,out,_), _ = render(body, settings, rate, block)
                delay = max(range(len(out)),key=lambda i:abs(out[i])) - max(range(len(inp)),key=lambda i:abs(inp[i]))
                assert delay == (0 if factor == 1 else 94), (rate,block,factor,delay)
                latency.append(dict(engine='native',rate=rate,ksmps=block,factor=factor,delay_samples=delay))
            code = ORCHESTRA + '''\ninstr Impulse
aIn=mpulse:a(1,0,.01)
aOut=juno60_filter(aIn,a(.49*sr),a(0),a(1),1,0,0)
out(aIn,aOut)
endin
'''
            inp,out,_ = render_udo(directory,code,'i "Impulse" 0 .04',rate,block)
            delay = max(range(len(out)),key=lambda i:abs(out[i])) - max(range(len(inp)),key=lambda i:abs(inp[i]))
            assert delay == 94, (rate,block,delay)
            latency.append(dict(engine='udo_settled',rate=rate,ksmps=block,factor=2,delay_samples=delay))

            voice = instruments[5].findtext('instrumentText')
            body = voice.replace('asig *= delay(aVca, 94/sr)',
                'aApplied = delay(aVca, 94/sr)\nasig *= aApplied')
            body = body.replace('blueMixerOut asig, asig', 'out(aEnv,aVca,aApplied)')
            values = dict(settings,vca_mode=1,env_attack=0,env_decay=0,env_sustain=0,env_release=0)
            (raw,gate,applied), release = render(body,values,rate,block)
            assert applied[:94] == (0.0,)*94
            error = max(abs(a-b) for a,b in zip(applied[94:],gate[:-94]))
            assert error < 1e-7, (rate,block,error,min(range(90,98),key=lambda d:
                max(abs(a-b) for a,b in zip(applied[d:],gate[:-d]))))
            rise10 = next(i for i,x in enumerate(gate) if x >= .1)
            rise90 = next(i for i,x in enumerate(gate) if x >= .9)
            fall10 = next(i for i,x in enumerate(gate[release:]) if x <= .1)
            fall1 = next(i for i,x in enumerate(gate[release:]) if x <= .01)
            assert abs((rise90-rise10)/rate-math.log(9)*TAU_ON) < 3/rate
            assert abs(fall10/rate-math.log(10)*TAU_OFF) < 3/rate
            assert abs(fall1/rate-math.log(100)*TAU_OFF) < 3/rate
            assert max(abs(x) for x in gate[release+round(.1*rate):]) == 0
            rows.append(dict(rate=rate,ksmps=block,rise10_90_ms=(rise90-rise10)*1000/rate,
                fall10_ms=fall10*1000/rate,fall1_ms=fall1*1000/rate))

        # Compile every voice in both modes and measure the common ENV routing.
        for number, instrument in enumerate(instruments,1):
            voice = instrument.findtext('instrumentText')
            assert 'aLinEnv' not in voice and 'iVcfEnvStart' not in voice
            for mode in (0,1):
                body = voice.replace('blueMixerOut asig, asig', 'out(aEnv,acut_env/kEnvModOct,aVca)')
                values = dict(settings,vca_mode=mode,vcf_env=5,env_attack=0,
                    env_decay=0,env_sustain=10,env_release=0)
                (generator,filter_env,vca), release = render(body,values)
                assert generator[0] == filter_env[0] == 0
                assert max(abs(a-b) for a,b in zip(generator,filter_env)) < 1e-12
                if mode == 0:
                    pole, b = 0.0, math.exp(-1/(48000*.01078))
                    for x,actual in zip(generator[:release+7000],vca[:release+7000]):
                        pole = (1-b)*x+b*pole
                        assert abs(actual-((12/49)*x+(37/49)*pole)) < 1e-9
                assert max(abs(x) for x in vca[release+9000:]) < 1e-6

        voice = instruments[5].findtext('instrumentText').replace(
            'blueMixerOut asig, asig','out(aEnv,acut_env/kEnvModOct,aVca)')
        for panel in (0,.6,.7,3,5):
            values = dict(settings,vca_mode=0,vcf_env=5,env_attack=panel)
            (generator,filter_env,_),_ = render(voice,values)
            assert generator[0] == filter_env[0] == 0
            assert max(abs(a-b) for a,b in zip(generator,filter_env)) < 1e-12
            position = round(.2*(.001+2.999*(panel/10)**3)*48000)
            assert .27 < filter_env[position] < .31
            controls.append(dict(attack_panel=panel,vcf_initial=filter_env[0],
                env_at_attack_20pct=generator[position],vcf_at_attack_20pct=filter_env[position]))

        for number in ('14','15','16'):
            values = dict(baseline['organs'][number],chorus_mode=0)
            for name,voice in [('before',baseline['voice']),('after',instruments[5].findtext('instrumentText'))]:
                body = voice.replace('blueMixerOut asig, asig','out(asig,asig,asig)')
                (audio,_,_), _ = render(body,values)
                clip = [x*.25 for x in audio[:24000]]
                clip += [0.0]*(38400-len(clip))
                audition += clip
                order.append(f'Organ {int(number)-13} {name}')
    for name,data in [('gate',rows),('latency',latency),('controls',controls)]:
        with (DEST/f'{name}.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    assert max(abs(x) for x in audition) < 1
    with wave.open(str(DEST/'organ_before_after.wav'),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(3);stream.setframerate(48000)
        stream.writeframes(b''.join(int(x*8388607).to_bytes(3,'little',signed=True) for x in audition))
    assert source == (PROJECT/'fixtures/voice.blue').read_bytes()
    (DEST/'metadata.json').write_text(json.dumps(dict(
        blue_sha256=hashlib.sha256(source).hexdigest(),
        plugin_sha256=hashlib.sha256((PLUGIN).read_bytes()).hexdigest(),
        audition_order=order,gain=.25,slot_seconds=.8),indent=2)+'\n')
    print('PASS: all six voices, shared ENV, VCA RC transfer/tails, asymmetric Gate, SRC latency/alignment')
    print(f'Organ before/after clips: {DEST/"organ_before_after.wav"}')


if __name__ == '__main__':
    main()
