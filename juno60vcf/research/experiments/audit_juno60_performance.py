#!/usr/bin/env python3
"""Benchmark instrument 6 and verify candidate optimizations without editing Blue.

python3 experiments/audit_juno60_performance.py --section all
Output: build/research-results/juno60_performance_audit.json. Uses the current native build.
"""
from research_paths import PLUGIN, RESULTS
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from check_juno60_startup import read_stereo

PROJECT = Path(__file__).resolve().parents[1]
POLE = 'aEnvPole = tone(aEnv, sr/(6.283185307179586)*cosinv(2-cosh(1/(sr*.01078))))'
MIX = 'aVca = (12/49)*aEnv + (37/49)*aEnvPole'
VCA = {
    'original': POLE + '\n' + MIX,
    'ntrpol': POLE + '\naVca = ntrpol(aEnv, aEnvPole, 37/49)',
    'filter2': 'iPole = exp(-1/(sr*.01078))\naVca = filter2(aEnv, 2, 1, 1-(37/49)*iPole, -(12/49)*iPole, -iPole)',
    'biquad': 'iPole = exp(-1/(sr*.01078))\naVca = biquad(aEnv, 1-(37/49)*iPole, -(12/49)*iPole, 0, 1, -iPole, 0)',
}


def chorus_candidates(definitions):
    inline = definitions
    polynomial = '(KD < 1 ? ((((.125*KD)-.3333333333333333)*KD-.25)*KD+1)*KD-.5 : (KD < 2 ? ((((-.04166666666666666*KD)+.3333333333333333)*KD-.9166666666666666)*KD+1)*KD-.3333333333333333 : 0))'
    for kd in ('kd1','kd2','kdm1','kdm2'):
        inline = inline.replace(f'blep_diff({kd})', polynomial.replace('KD',kd))
    triangle = definitions.replace('kdepth_1 * (1.0 - (4.0 * abs(frac(aph + 0.5) - 0.5)))', '-amod_l').replace('kdepth_2 * (1.0 - (4.0 * abs(frac(aph + 0.5) - 0.5)))', '-amod_l')
    shared = definitions.replace('awet_r = bbd_line(abbd_in, afclk_r, i_stages)', 'if kmode >= 2.5 then\n awet_r = awet_l\nelse\n awet_r = bbd_line(abbd_in, afclk_r, i_stages)\nendif')
    return dict(inline_blep=inline, triangle=triangle, shared_bbd=shared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--section', choices=('all', 'vca', 'voice', 'chorus', 'check', 'followup'), default='all')
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    assert args.repeats > 0
    blue = (PROJECT/'fixtures/voice.blue').read_bytes()
    root = ET.fromstring(blue)
    inst = root.find(".//instrumentAssignment[@arrangementId='6']/instrument")
    rate = int(root.findtext('projectProperties/sampleRate'))
    block = int(root.findtext('projectProperties/ksmps'))
    voice = inst.findtext('instrumentText').replace('blueMixerOut asig, asig', 'gaLeft += asig\ngaRight += asig')
    # Keep the pre-optimization network as the benchmark baseline after the
    # verified filter2 candidate has been applied to the actual instrument.
    voice = voice.replace('  '+VCA['filter2'].replace('\n', '\n  '), '  '+POLE+'\n  '+MIX)
    post = re.sub(r'^aLeft, aRight\s+blueMixerIn', 'aLeft = gaLeft\naRight = gaRight\ngaLeft = 0\ngaRight = 0', inst.findtext('alwaysOnInstrumentText'))
    post = post.replace('blueMixerOut a1, a2', 'out(a1, a2)')
    definitions = []
    for udo in inst.findall('opcodeList/udo'):
        outputs = udo.findtext('outTypes').replace(',', '').replace(' ', '')
        outputs = '('+','.join(outputs)+')' if len(outputs) > 1 else outputs
        definitions.append(f"opcode {udo.findtext('opcodeName')}({udo.findtext('inputArguments')}):{outputs}\n{udo.findtext('codeBody')}\nendop\n")
    definitions = '\n'.join(definitions)
    settings = {p.get('name'): p.get('value') for p in inst.findall('parameterList/parameter')}
    stored_settings = dict(settings)
    # Match Blue's real compilation: every panel parameter remains a global k variable.
    # Fixed stress patch includes every source and moving filter cutoff/PWM.
    settings.update(dco_saw_enabled=1, dco_pulse_enabled=1, dco_sub_enabled=1,
                    dco_noise_enabled=1, dco_sub=5, dco_noise=1, dco_pwm=5,
                    dco_pwm_source=0, dco_lfo=1, vcf_freq=5, vcf_env=4,
                    vcf_res=7, vcf_lfo=1, vcf_kybd=5, vcf_invert=0,
                    env_attack=1, env_decay=5, env_sustain=7, env_release=1,
                    vca_mode=0, vca_level_adjust=5, hpf_mode=0, chorus_mode=1,
                    lfo_rate=4, lfo_delay_time=0, lfo_trig=1, lfo_trigger_mode=0)
    plugin = PLUGIN
    destination = RESULTS / 'juno60_performance_audit.json'
    results = json.loads(destination.read_text()) if destination.exists() and args.section != 'all' else {}
    results.pop('_chorus_candidates', None)
    results['metadata'] = dict(blue_sha256=hashlib.sha256(blue).hexdigest(),
        plugin_sha256=hashlib.sha256(plugin.read_bytes()).hexdigest(), rate=rate, ksmps=block,
        repeats='See length of runs_seconds in each case', settings=settings, stored_settings=stored_settings,
        method='Median offline wall time; Csound startup included; serial runs, no audio device. LFO channel matched to exercise modulation.')

    def substitute(text):
        text = text.replace('<INSTR_ID>', '6')
        for key in settings:
            text = text.replace(f'<{key}>', 'gkPanel_'+key)
        assert not re.findall(r'<[A-Za-z_]\w*>', text)
        return text

    with tempfile.TemporaryDirectory(prefix='juno60-perf-') as temporary:
        directory = Path(temporary)
        env = dict(os.environ, CS_USER_PLUGINDIR=temporary, OPCODE7DIR=temporary, OPCODE7DIR64=temporary)
        def run(body, score, defs='', globals_='', sr=rate, ksmps=block, audio=False, verbose=False):
            source, wav = directory/'probe.csd', directory/'probe.wav'
            source.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0 --sample-accurate
</CsOptions>
<CsInstruments>
sr = {sr}
ksmps = {ksmps}
nchnls = 2
0dbfs = 1
seed 1234
{globals_}
{defs}
{body}
</CsInstruments>
<CsScore>
{score}
e
</CsScore>
</CsoundSynthesizer>
''')
            cmd = ['csound', f'--opcode-lib={plugin}']
            cmd += ['-W', '--format=double', '-o', str(wav)] if audio else ['-n']
            if verbose:
                cmd += ['-v', '--syntax-check-only']
            start = time.perf_counter()
            result = subprocess.run(cmd+[str(source)], env=env, capture_output=True, text=True, timeout=60)
            elapsed = time.perf_counter()-start
            assert result.returncode == 0, result.stderr
            if verbose:
                return result.stdout+result.stderr
            return read_stereo(wav)[:2] if audio else elapsed

        def benchmark(name, body, score, **kw):
            run(body, score, **kw)  # warm filesystem and executable caches
            values = [run(body, score, **kw) for _ in range(args.repeats)]
            result = dict(name=name, median_seconds=statistics.median(values), runs_seconds=values)
            print(f'{name}: {result["median_seconds"]:.4f}s', flush=True)
            return result

        if args.section in ('all', 'vca'):
            rows = []
            score = '\n'.join(f'i "Probe" 0 20' for _ in range(32))
            for name, network in VCA.items():
                body = 'instr Probe\naEnv = transegr:a(0,.001,-1,1,.2,-4.2,.7,.1,-4.2,0)\n'+network+'\nout(aVca,aVca)\nendin'
                rows.append(benchmark('vca_'+name, body, score))
            results['vca'] = rows

        if args.section in ('all', 'voice'):
            rows = []
            for count in (1, 6, 16):
                for name in ('original', 'no_vcf', 'no_vca', 'ntrpol', 'pulse_scalar'):
                    candidate = voice
                    if name == 'no_vcf':
                        candidate = candidate.replace('asig = juno60vcf(asig, acutoff, kResonance, 1, 1, ioversample)', '; VCF bypass for cost attribution')
                    elif name == 'no_vca':
                        start = candidate.index(';; VCA')
                        candidate = candidate[:start] + '\ngaLeft += asig\ngaRight += asig\nskipInit:'
                    elif name == 'ntrpol':
                        candidate = candidate.replace(MIX, 'aVca = ntrpol(aEnv,aEnvPole,37/49)')
                    elif name == 'pulse_scalar':
                        candidate = candidate.replace('asig -= vco2(1, kFreq, 2, 1-kPwmWidth) + a(2*kPwmWidth-1)', 'asig -= vco2(1,kFreq,2,1-kPwmWidth)\nasig -= 2*kPwmWidth-1')
                    values = dict(settings, chorus_mode=0)
                    globals_ = '\n'.join(f'gkPanel_{k} init {v}' for k,v in values.items())+'\ngaLeft init 0\ngaRight init 0'
                    body = 'instr Voice\n'+substitute(candidate)+'\nendin\ninstr Output\n'+substitute(post)+'\nendin'
                    score = '\n'.join(f'i "Voice" 0 4 {48+(i%12)} -18' for i in range(count))+'\ni "Output" 0 4.3'
                    rows.append(benchmark(f'voice_{count}_{name}', body, score, defs=definitions, globals_=globals_))
            results['voice'] = rows

        if args.section in ('all', 'chorus'):
            rows = []
            # Inline only the hot four BLEP helper calls; no algorithm change.
            for mode in (0,1,3):
                for name, defs in [('original',definitions), *chorus_candidates(definitions).items()]:
                    if mode == 0 and name != 'original' or mode == 1 and name == 'shared_bbd' or mode == 3 and name == 'triangle':
                        continue
                    body = f'instr Probe\naIn = oscili(.2,220)\naL,aR = juno_chorus(aIn,k({mode}),.01)\nout(aL,aR)\nendin' if mode else 'instr Probe\naIn=oscili(.2,220)\nout(aIn,aIn)\nendin'
                    rows.append(benchmark(f'chorus_{mode}_{name}',body,'i "Probe" 0 8',defs=defs))
            results['chorus'] = rows

        if args.section in ('all', 'check'):
            rows=[]
            for sr, ksmps in ((44100,64),(48000,32),(96000,64),(48000,1),(48000,128)):
                for signal in ('transegr:a(0,.001,-1,1,.002,-4.2,.7,.002,-4.2,0)', 'mpulse:a(1,0,.003)', 'random:a(-1,1)'):
                    def vca_probe(network):
                        return run('instr Probe\naEnv = '+signal+'\n'+network+'\nout(aVca,aVca)\nendin','i "Probe" 0 .04',sr=sr,ksmps=ksmps,audio=True)[0]
                    original=vca_probe(VCA['original'])
                    for name,network in VCA.items():
                        candidate=vca_probe(network)
                        assert len(candidate)==len(original)
                        error=max(abs(a-b) for a,b in zip(candidate,original))
                        assert error < 2e-9,(name,sr,ksmps,error)
                        rows.append(dict(candidate=name,sr=sr,ksmps=ksmps,signal=signal,max_abs_error=error))
            results['vca_parity']=rows

            # Candidate chorus comparisons use identical seeded independent hiss paths.
            candidates=chorus_candidates(definitions)
            chorus_rows=[]
            for mode in (1,2,3,4):
                body=f'instr Probe\naIn=oscili(.2,220)\naL,aR=juno_chorus(aIn,k({mode}),.01)\nout(aL,aR)\nendin'
                original=run(body,'i "Probe" 0 .2',defs=definitions,audio=True)
                for name,defs in candidates.items():
                    candidate=run(body,'i "Probe" 0 .2',defs=defs,audio=True)
                    error=max(abs(a-b) for xs,ys in zip(original,candidate) for a,b in zip(xs,ys))
                    assert error < 2e-10,(name,mode,error)
                    chorus_rows.append(dict(candidate=name,mode=mode,max_abs_error=error))
            results['chorus_parity']=chorus_rows
            print('PASS: VCA transfer/impulse/noise and chorus candidate parity',flush=True)
        if args.section in ('all', 'followup'):
            rows = []
            for label, values in [('stored_patch', stored_settings), ('stress_patch', settings)]:
                values = dict(values, chorus_mode=0)
                globals_ = '\n'.join(f'gkPanel_{k} init {v}' for k,v in values.items())+'\ngaLeft init 0\ngaRight init 0'
                bodies = {}
                for name, network in [('original',VCA['original']), ('filter2',VCA['filter2'])]:
                    candidate = voice.replace(POLE+'\n  '+MIX, network)
                    if name == 'filter2':
                        assert 'filter2(aEnv' in candidate
                    bodies[name] = 'instr Voice\n'+substitute(candidate)+'\nendin\ninstr Output\n'+substitute(post)+'\nendin'
                score = '\n'.join(f'i "Voice" 0 4 {48+i} -18' for i in range(6))+'\ni "Output" 0 4.3'
                for body in bodies.values():
                    run(body, score, defs=definitions, globals_=globals_)
                timings = {name: [] for name in bodies}
                # Alternate order to reduce timing drift between candidates.
                for repeat in range(args.repeats):
                    order = list(bodies) if repeat%2 == 0 else list(reversed(bodies))
                    for name in order:
                        timings[name].append(run(bodies[name],score,defs=definitions,globals_=globals_))
                for name, values_ in timings.items():
                    result = dict(name=label+'_'+name,median_seconds=statistics.median(values_),runs_seconds=values_)
                    rows.append(result)
                    print(result['name'], result['median_seconds'], flush=True)
            results['full_voice_filter2'] = rows
            parity = []
            for mode in (0,1):
                globals_ = '\n'.join(f'gkPanel_{k} init {v}' for k,v in dict(settings,chorus_mode=0,vca_mode=mode,dco_pwm_source=2).items())+'\ngaLeft init 0\ngaRight init 0'
                clips = {}
                for name,network in VCA.items():
                    candidate=voice.replace(POLE+'\n  '+MIX,network)
                    body='instr Voice\n'+substitute(candidate)+'\nendin\ninstr Output\n'+substitute(post)+'\nendin'
                    clips[name]=run(body,'i "Voice" .0013 .1 60 -6\ni "Output" 0 .5',defs=definitions,globals_=globals_,audio=True)
                for name,clip in clips.items():
                    error=max(abs(a-b) for xs,ys in zip(clips['original'],clip) for a,b in zip(xs,ys))
                    assert error<2e-9,(mode,name,error)
                    parity.append(dict(mode=mode,candidate=name,max_abs_error=error))
            results['full_voice_parity']=parity
            shared=chorus_candidates(definitions)['shared_bbd']
            body='instr Probe\naIn=oscili(.2,220)\nkMode=(timeinsts()<.05 ? 1 : 3)\naL,aR=juno_chorus(aIn,kMode,.01)\nout(aL,aR)\nendin'
            original=run(body,'i "Probe" 0 .2',defs=definitions,audio=True)
            candidate=run(body,'i "Probe" 0 .2',defs=shared,audio=True)
            error=max(abs(a-b) for xs,ys in zip(original,candidate) for a,b in zip(xs,ys))
            results['shared_bbd_mode_change_error']=error
            assert error>1e-8, 'Expected independent BBD histories to differ at mode change'
            print('PASS: full voice parity; shared BBD changes mode-switch transients:',error,flush=True)
    assert blue==(PROJECT/'fixtures/voice.blue').read_bytes(), 'Blue source changed during audit'
    destination.write_text(json.dumps(results,indent=2)+'\n')
    print(destination,flush=True)


if __name__=='__main__':
    main()
