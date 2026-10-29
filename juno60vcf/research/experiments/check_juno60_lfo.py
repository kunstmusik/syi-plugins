#!/usr/bin/env python3
"""Verify the actual Blue LFO blocks with distinct voice/output IDs and channels."""
from research_paths import PLUGIN
import os
import math
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from check_juno60_startup import read_stereo
from check_juno60_patches import read_taps

PROJECT = Path(__file__).resolve().parents[1]


def main():
    root = ET.parse(PROJECT/'fixtures/voice.blue').getroot()
    assignments = root.findall('.//instrumentAssignment')
    blocks, names = [], []
    for assignment in assignments:
        number = int(assignment.get('arrangementId'))
        instrument = assignment.find('instrument')
        voice = instrument.findtext('instrumentText')
        post = instrument.findtext('alwaysOnInstrumentText')
        reader = re.search(r'^Sjno60Lfo.*?^klfo = kLfoMod \* kLfoGain',voice,re.M|re.S).group()
        writer = re.search(r'^iJno60Rates.*?^chnset kJno60Gain, "[^"\n]+"',post,re.M|re.S).group()
        # Model Blue's generated numeric IDs, not a single replacement in both blocks.
        reader = reader.replace('<INSTR_ID>',str(number))
        writer = writer.replace('<INSTR_ID>',str(number+len(assignments)))
        writer = writer.replace('<lfo_rate>',str(number))
        for key,value in {'lfo_trigger_mode':'gkMode','lfo_trig':'gkTrigger','lfo_delay_time':'gkDelay'}.items():
            writer = writer.replace(f'<{key}>',value)
        name = re.search(r'Sjno60Lfo = "([^"]+)"',reader).group(1)
        assert f'Sjno60Lfo = "{name}"' in writer
        names.append(name)
        blocks += [f'instr {number}\n{reader}\nout(a(kLfoVal),a(kLfoVal))\nendin',
                   f'instr {number+len(assignments)}\n{writer}\nendin']
    assert len(names)==len(set(names)), 'Synth LFO channels must be independent'
    with tempfile.TemporaryDirectory(prefix='juno60-lfo-') as temporary:
        directory=Path(temporary)
        env=dict(os.environ,CS_USER_PLUGINDIR=temporary,OPCODE7DIR=temporary,OPCODE7DIR64=temporary)
        for number,name in enumerate(names,1):
            score='\n'.join(f'i {n+len(names)} 0 .5' for n in range(1,len(names)+1))
            score+=f'\ni {number} 0 .5\ni 99 0 .5'
            # Reference the matching producer directly; both outputs contain the
            # same intentional one-block delay from the original execution order.
            reference=f'instr 99\nkReference chnget "{name}"\nout(-a(kReference),a(0))\nendin'
            source,wav=directory/'probe.csd',directory/'probe.wav'
            source.write_text('<CsoundSynthesizer>\n<CsOptions>\n-d -m0\n</CsOptions>\n<CsInstruments>\nsr=44100\nksmps=64\nnchnls=2\n0dbfs=1\ngkMode init 0\ngkTrigger init 0\ngkDelay init 0\n'+ '\n'.join(blocks)+'\n'+reference+'\n</CsInstruments>\n<CsScore>\n'+score+'\ne\n</CsScore>\n</CsoundSynthesizer>\n')
            result=subprocess.run(['csound','-W','--format=double','-o',str(wav),str(source)],env=env,capture_output=True,text=True,timeout=10)
            assert result.returncode==0,result.stderr
            left,right,_=read_stereo(wav)
            # The reference executes after the producers, so compare channel
            # values separately with the known one-block scheduling delay.
            expected=[b-a for a,b in zip(left,right)]
            assert max(abs(x) for x in right)>.1,(name,'LFO never reached the voice')
            assert max(abs(a-b) for a,b in zip(right[64:],expected[:-64]))<1e-12,name
            print(f'PASS: voice {number} / output {number+len(names)} share {name}',flush=True)

        # Exercise the actual shared block. Release tails must not count as
        # held keys, overlapping notes must not restart AUTO, and a MANUAL
        # press must start its own fade even after a note has aged.
        delay_position = 2.5 + 2.5*(.2-.061)/(.406-.061)  # exactly .2 seconds
        fade = .047 + (.213-.047)*(.2-.061)/(.406-.061)
        for number in range(1,len(names)+1):
            reader = blocks[2*(number-1)].split('\nout(')[0]+'\nxtratim .25\nendin'
            writer = blocks[2*(number-1)+1]
            traces = []
            for mode,delay in ((0,delay_position),(1,delay_position),(0,0),(1,0)):
                control = '''instr 99
kNow timeinsts
gkTrigger = ((kNow >= .35 && kNow < .65) || (kNow >= .8 && kNow < 1.15) ? 1 : 0)
endin'''
                monitor = f'''instr 100
kRaw chnget "jno60_lfo_{number}"
kGain chnget "jno60_lfo_gain_{number}"
kMod chnget "jno60_lfo_mod_{number}"
out(upsamp(kRaw),upsamp(kGain),upsamp(kMod))
endin'''
                source.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0 --sample-accurate
</CsOptions>
<CsInstruments>
sr=48000
ksmps=32
nchnls=3
0dbfs=1
gkMode init {mode}
gkTrigger init 0
gkDelay init {delay}
{reader}
{writer}
{control}
{monitor}
</CsInstruments>
<CsScore>
i {number+len(names)} 0 1.4
i {number} 0 .8
i {number} .1 .7
i {number} .9 .4
i 99 0 1.4
i 100 0 1.4
e
</CsScore>
</CsoundSynthesizer>
''')
                result=subprocess.run(['csound','-W','--format=double','-o',str(wav),str(source)],env=env,capture_output=True,text=True,timeout=10)
                assert result.returncode==0,result.stderr
                (raw,gain,mod),rate=read_taps(wav)
                assert max(abs(b-math.tanh(2*a)/math.tanh(2)) for a,b in zip(raw,mod))<1e-12
                traces.append(raw)
                def at(seconds): return gain[round(seconds*rate)]
                if mode == 0 and delay:
                    for seconds,expected_gain in ((.19,0),(.21,.01/fade),(.3,.1/fade),(.33,1),(.81,0),(.99,0),(1.12,.02/fade),(1.25,1)):
                        assert abs(at(seconds)-expected_gain)<.015,(number,mode,seconds,at(seconds))
                    changes=[abs(b-a) for a,b in zip(gain[:int(.7*rate)-32],gain[32:int(.7*rate)])]
                    assert max(changes)<.006, 'AUTO must fade in continuously'
                elif mode == 1 and delay:
                    for seconds,expected_gain in ((.3,0),(.36,.05),(.45,.5),(.56,1),(.66,0),(.81,.05),(.9,.5),(1.01,1)):
                        assert abs(at(seconds)-expected_gain)<.01,(number,mode,seconds,at(seconds))
                elif mode == 0:
                    assert min(gain[:int(1.39*rate)])==max(gain)==1
                else:
                    for seconds,expected_gain in ((.3,0),(.36,1),(.66,0),(.81,1),(1.2,0)):
                        assert at(seconds)==expected_gain,(number,mode,seconds,at(seconds))
            assert all(trace==traces[0] for trace in traces), 'Delay/trigger must not affect raw PWM LFO'
            print(f'PASS: synth {number} AUTO hold/legato/release, MANUAL press/repress, zero delay, raw PWM',flush=True)

        # Verify the actual DCO-frequency expression without a filter or chorus.
        voice=assignments[-1].findtext('instrument/instrumentText')
        depth=re.search(r'^kPitchVoltage = .*\n^kPitchCents = .*$',voice,re.M).group()
        frequency=re.search(r'^kFreq = .*$',voice,re.M).group()
        reader=re.search(r'^Sjno60Lfo.*?^klfo = kLfoMod \* kLfoGain',voice,re.M|re.S).group()
        post=assignments[-1].findtext('instrument/alwaysOnInstrumentText')
        writer=re.search(r'^iJno60Rates.*?^chnset kJno60Gain, "[^"\n]+"',post,re.M|re.S).group()
        for key,value in dict(lfo_rate=5,lfo_trigger_mode=0,lfo_trig=0,lfo_delay_time=0).items():
            writer=writer.replace(f'<{key}>',str(value))
        for panel,expected in ((0,0),(1,.531),(1.5,7.91),(5,97.159),(10,225)):
            source.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0
</CsOptions>
<CsInstruments>
sr=48000
ksmps=32
nchnls=2
0dbfs=1
instr 1
ifreq=440
{depth.replace('<dco_lfo>',str(panel))}
{reader}
{frequency}
out(upsamp(1200*log(kFreq/ifreq)/log(2)),upsamp(kLfoVal))
endin
instr 2
{writer}
endin
</CsInstruments>
<CsScore>
i 1 0 3
i 2 0 3
e
</CsScore>
</CsoundSynthesizer>
''')
            result=subprocess.run(['csound','-W','--format=double','-o',str(wav),str(source)],env=env,capture_output=True,text=True,timeout=10)
            assert result.returncode==0,result.stderr
            cents,raw,rate=read_stereo(wav)
            assert abs(max(cents)-expected)<.015 and abs(min(cents)+expected)<.015,(panel,min(cents),max(cents))
            controls=raw[::32]
            peaks=[i for i in range(1,len(controls)-1) if controls[i-1]<controls[i] and controls[i]>=controls[i+1]]
            assert abs((len(peaks)-1)*rate/(32*(peaks[-1]-peaks[0]))-3.4147)<.01
        print('PASS: actual DCO: Brass +/-7.91 cents, continuous depth 0/1/5/10, rate-5 3.4147 Hz',flush=True)

        # Exercise live VCF depth changes in one note, including zero after
        # nonzero, repeated positions, and out-of-range clamp behavior.
        # All six synths must use the same scalar mapping.
        vcf_blocks = [re.search(r'^kLfoVoltage = .*?^endif',
                      a.findtext('instrument/instrumentText'),re.M|re.S).group()
                      for a in assignments]
        assert all(block==vcf_blocks[0] for block in vcf_blocks)
        vcf_depth = vcf_blocks[0].replace('<vcf_lfo>','kPanel')
        cut_sum = re.search(r'^kcut = .*$',voice,re.M).group()
        cutoff = re.search(r'^acutoff = .*$',voice,re.M).group()
        positions = [0,.1,1.5,2.5,5,7.5,10,5,0,-1,11,0]
        source.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0
</CsOptions>
<CsInstruments>
sr=48000
ksmps=32
nchnls=3
0dbfs=1
giPanels[] fillarray {','.join(map(str,positions))}
instr 1
kPanel = giPanels[min(int(timeinsts()/.4),{len(positions)-1})]
{vcf_depth}
{reader}
kcut_freq = 3.5*16.6667/10
kcut_kybd = 0
acut = 0
{cut_sum}
{cutoff}
out(upsamp(kLfoModOct),acutoff,upsamp(klfo))
endin
instr 2
{writer}
endin
</CsInstruments>
<CsScore>
i 1 0 {len(positions)*.4}
i 2 0 {len(positions)*.4}
e
</CsScore>
</CsoundSynthesizer>
''')
        result=subprocess.run(['csound','-W','--format=double','-o',str(wav),str(source)],env=env,capture_output=True,text=True,timeout=10)
        assert result.returncode==0,result.stderr
        (depths,cutoffs,lfo),rate=read_taps(wav)
        for index,panel in enumerate(positions):
            voltage=min(max(panel/2,0),5)
            expected=3.46*.06/4.4*(math.log1p(math.exp((voltage-.6)/.06))-math.log1p(math.exp(-10)))
            start,stop=round((index*.4+.02)*rate),round((index*.4+.38)*rate)
            assert max(abs(x-expected) for x in depths[start:stop])<1e-10,(panel,'stale depth cache')
            for j in range(start,stop,32):
                command=7.8*math.exp(.6931472*(3.5*16.6667/10+lfo[j]*expected))
                assert abs(cutoffs[j]-command)<1e-8,(panel,'cutoff modulation mismatch')
        full=cutoffs[round(2.4*rate)+32:round(2.8*rate)-32]
        assert 40<min(full)<50 and 4000<max(full)<5000,(min(full),max(full))
        print(f'PASS: VCF live depth/clamps/reset; FREQ 3.5, depth 10 requests {min(full):.2f}..{max(full):.2f} Hz',flush=True)

        # Check that the native resonant filter realizes the endpoint requests,
        # rather than relying solely on the cutoff-control expression.
        for sign,limits in ((-1,(40,50)),(1,(4000,5000))):
            source.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0
</CsOptions>
<CsInstruments>
sr=48000
ksmps=32
nchnls=2
0dbfs=1
instr 1
kPanel = 10
{vcf_depth}
klfo = {sign}
kcut_freq = 3.5*16.6667/10
kcut_kybd = 0
acut = 0
{cut_sum}
{cutoff}
aSignal = juno60vcf(a(0),acutoff,1,1,1,4)
out(aSignal,acutoff)
endin
</CsInstruments>
<CsScore>
i 1 0 3
e
</CsScore>
</CsoundSynthesizer>
''')
            result=subprocess.run(['csound',f'--opcode-lib={PLUGIN}',
                                   '-W','--format=double','-o',str(wav),str(source)],
                                  env=env,capture_output=True,text=True,timeout=10)
            assert result.returncode==0,result.stderr
            signal,command,rate=read_stereo(wav)
            tail=signal[-rate:]
            crossings=[i-tail[i]/(tail[i+1]-tail[i])
                       for i in range(len(tail)-1) if tail[i]<=0<tail[i+1]]
            assert len(crossings)>2,'Native filter did not self-oscillate'
            frequency=(len(crossings)-1)*rate/(crossings[-1]-crossings[0])
            assert limits[0]<frequency<limits[1],(sign,frequency)
            print(f'PASS: native VCF endpoint {frequency:.2f} Hz (request {command[-1]:.2f} Hz)',flush=True)


if __name__=='__main__':
    main()
