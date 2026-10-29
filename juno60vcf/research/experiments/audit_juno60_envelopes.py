#!/usr/bin/env python3
"""Research probes of actual instrument 6 envelopes/attacks; does not edit DSP.

Candidate changes are confined to temporary CSDs. Outputs control/attack metrics
and an audition WAV; circuit timing is an ideal component-derived estimate.
"""
from research_paths import PLUGIN, RESULTS
import argparse
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

PROJECT = Path(__file__).resolve().parents[1]
DEST = RESULTS / 'juno60_envelope_audit'
RATE = 48000
HOLD = .3
TAU_ON = .22e-6 / (1/5600 + 1/22000)
TAU_OFF = .22e-6 * 22000
GATE = 'transegr:a(0, .006, -4.2, 1, .006, -4.2, 0)'
RC_GATE = f'''opcode audit_gate():a
setksmps 1
xtratim(.06)
kOn = 1-release()
kGain init 0
kTau = (kOn == 1 ? {TAU_ON} : {TAU_OFF})
kGain = kOn + (kGain-kOn)*exp(-1/(sr*kTau))
xout(a(kGain))
endop
'''


def rms(values):
    return math.sqrt(sum(x*x for x in values)/len(values))


def save_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', action='store_true',
                        help='reproduce the original audit from its saved voice/settings')
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    source = PROJECT/'fixtures/voice.blue'
    source_bytes = source.read_bytes()
    instrument = ET.fromstring(source_bytes).find(
        ".//instrumentAssignment[@arrangementId='6']/instrument")
    settings = {p.get('name'): p.get('value') for p in instrument.findall('parameterList/parameter')}
    dropdowns = {w.findtext('objectName'): {'id:'+item.get('uniqueId'): str(i)
        for i,item in enumerate(w.findall('bsbDropdownItemList/bsbDropdownItem'))}
        for w in instrument.findall('.//bsbObject')}
    organs = {}
    for preset in instrument.findall(".//presetGroup[@name='Factory']/preset"):
        number = int(preset.get('name').split()[0])
        if number in (14,15,16):
            organs[number] = {entry.get('name'): dropdowns[entry.get('name')][entry.text]
                if entry.text.startswith('id:') else {'true':'1','false':'0'}.get(entry.text,entry.text)
                for entry in preset.findall('setting')}
    voice = instrument.findtext('instrumentText')
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if args.before:
        snapshot = json.loads((PROJECT/'fixtures/envelope_baseline.json').read_text())
        voice, settings = snapshot['voice'], snapshot['settings']
        organs = {int(n): values for n, values in snapshot['organs'].items()}
        source_hash = snapshot['project_sha256']
    if 'aLinEnv = linsegr' not in voice:
        parser.error('use --before for the historical audit, or check_juno60_envelopes.py for current DSP')
    times = voice.split('; Envelope Attack:', 1)[1].split('tigoto skipInit', 1)[0]
    times = '; Envelope Attack:'+times
    curve = re.search(r'^aEnv = (.*)$', voice, re.M).group(1)
    linear = re.search(r'^aLinEnv = (.*)$', voice, re.M).group(1)
    controls, attacks, audition, latency = [], [], [], []
    organ_clips = {}
    traces = {}
    with tempfile.TemporaryDirectory(prefix='juno60-envelope-audit-') as temporary:
        directory = Path(temporary)
        env = dict(os.environ, CS_USER_PLUGINDIR=temporary,
                   OPCODE7DIR=temporary, OPCODE7DIR64=temporary)

        def render(body, values, duration=HOLD, native=False):
            for key, value in values.items():
                body = body.replace(f'<{key}>', str(value))
            body = body.replace('<INSTR_ID>', '6')
            assert not re.findall(r'<[A-Za-z_]\w*>', body)
            csd, output = directory/'probe.csd', directory/'probe.wav'
            csd.write_text(f'''<CsoundSynthesizer>
<CsOptions>
-d -m0 --sample-accurate
</CsOptions>
<CsInstruments>
sr={RATE}
ksmps=32
nchnls=3
0dbfs=1
seed 1234
{RC_GATE}
instr Lfo
kLfo = lfo:k(1, 0.3*pow(20/0.3, {values['lfo_rate']}/10), 1)
chnset(kLfo, "jno60_lfo_6")
endin
instr Voice
{body}
endin
</CsInstruments>
<CsScore>
i "Lfo" 0 {duration+1}
i "Voice" 0 {duration} 60 0
e
</CsScore>
</CsoundSynthesizer>
''')
            command = ['csound', '-W', '--format=double', '-o', str(output)]
            if native:
                command += [f'--opcode-lib={PLUGIN}']
            result = subprocess.run(command+[str(csd)], env=env, capture_output=True,
                                    text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            taps, rate = read_taps(output)
            assert rate == RATE
            return taps

        for panel in (0, .6, .7, 3, 5, 10):
            values = dict(settings, env_attack=panel, env_decay=4, env_sustain=4, env_release=3)
            body = times+f'\naEnv = {curve}\naFilterEnv = {linear}\naGate = {GATE}\n'
            body += 'out(aEnv, aFilterEnv, aGate)'
            taps = render(body, values, 3.2 if panel == 10 else HOLD)
            attack = .001+2.999*(panel/10)**3
            position = round(.2*attack*RATE)
            controls.append(dict(panel_attack=panel, nominal_attack_ms=attack*1000,
                        vca_at_attack_20pct=taps[0][position],
                        vcf_at_attack_20pct=taps[1][position],
                        vcf_initial=taps[1][0],
                        gate_90pct_ms=next(i/RATE*1000 for i,x in enumerate(taps[2]) if x >= .9)))
            if panel in (0,3):
                traces[f'envelope_{panel}'] = taps
                save_csv(DEST/f'envelope_{panel}.csv', [dict(time=i/RATE, env=taps[0][i],
                       vcf=taps[1][i], gate=taps[2][i]) for i in range(len(taps[0]))])
        # The gate release should remain its own 6ms, despite the long ENV tail.
        gate = traces['envelope_3'][2]
        release_index = round(HOLD*RATE)
        tail = gate[release_index:]
        assert next(i/RATE for i,x in enumerate(tail) if x <= .001) < .008

        body = f'aOld = {GATE}\naRC = audit_gate()\nout(aOld, aRC, a(0))'
        old, rc, _ = render(body, settings)
        release_metrics = []
        for name, signal in [('current_gate', old), ('circuit_RC_estimate', rc)]:
            release_metrics.append(dict(name=name,
                rise10_ms=next(i/RATE*1000 for i,x in enumerate(signal) if x >= .1),
                rise90_ms=next(i/RATE*1000 for i,x in enumerate(signal) if x >= .9),
                fall10_ms=next(i/RATE*1000 for i,x in enumerate(signal[release_index:]) if x <= .1),
                fall1_ms=next(i/RATE*1000 for i,x in enumerate(signal[release_index:]) if x <= .01)))
        save_csv(DEST/'gate_metrics.csv', release_metrics)
        save_csv(DEST/'gate_trace.csv', [dict(time=i/RATE, current=old[i],
                    circuit_rc=rc[i]) for i in range(min(len(old), len(rc)))])

        for factor in (1,2,4):
            impulse = f'aIn = mpulse:a(1, 0)\naOut = juno60vcf(aIn, 23520, 0, 1, 1, {factor}, 0)\nout(aIn, aOut, a(0))'
            inp, out, _ = render(impulse, settings, .03, native=True)
            peak = max(range(len(out)), key=lambda i: abs(out[i]))
            latency.append(dict(oversampling=factor, impulse_peak_sample=peak,
                                impulse_peak_ms=peak/RATE*1000))
        save_csv(DEST/'latency.csv', latency)
        variants = [
            ('current_gate', {}, 'current', 0),
            ('current_ENV', {'vca_mode':0}, 'current', 0),
            ('gate_no_filter_ENV', {'vcf_env':0}, 'current', 0),
            ('gate_circuit_RC', {}, 'rc_gate', 0),
            ('gate_shared_ENV', {}, 'shared_env', 0),
            ('gate_prerun', {}, 'current', round(64/(440*2**((60-69)/12))*RATE)/RATE),
            ('gate_no_filter_ENV_prerun', {'vcf_env':0}, 'current',
             round(64/(440*2**((60-69)/12))*RATE)/RATE),
            ('gate_no_filter_ENV_open', {'vcf_env':0,'vcf_freq':10}, 'current', 0),
        ]
        preroll = round(64/(440*2**((60-69)/12))*RATE)/RATE
        for number, factory in organs.items():
            base = dict(factory, chorus_mode=0)
            variants += [
                (f'organ_{number}_current', base, 'current', 0),
                (f'organ_{number}_circuit_RC', base, 'rc_gate', 0),
                (f'organ_{number}_filter_1x', base, 'filter_1x', 0),
                (f'organ_{number}_aligned_gate', base, 'aligned_gate', 0),
                (f'organ_{number}_shared_ENV', base, 'shared_env', 0),
                (f'organ_{number}_prerun', base, 'current', preroll),
                (f'organ_{number}_no_filter_ENV', dict(base,vcf_env=0), 'current', 0),
                (f'organ_{number}_no_filter_ENV_prerun', dict(base,vcf_env=0), 'current', preroll),
            ]
        for name, overrides, variant, warm in variants:
            values = dict(settings, vca_mode=1, dco_lfo=0, vcf_lfo=0, chorus_mode=0)
            values.update(overrides)
            body = voice.replace('asig = juno60vcf(', 'aPre = asig\nasig = juno60vcf(')
            body = body.replace(';; VCA', 'aPost = asig\n;; VCA')
            body = body.replace('blueMixerOut asig, asig', 'out(aPre, aPost, asig)')
            if variant == 'rc_gate':
                body = body.replace(GATE, 'audit_gate()')
            elif variant == 'filter_1x':
                body = body.replace('juno60vcf(asig, acutoff, kResonance, 1)',
                                    'juno60vcf(asig, acutoff, kResonance, 1, 1, 1)')
            elif variant == 'aligned_gate':
                delay = (latency[1]['impulse_peak_sample']-latency[0]['impulse_peak_sample'])/RATE
                body = body.replace(GATE, f'delay({GATE}, {delay})')
            elif variant == 'shared_env':
                body = body.replace(f'aLinEnv = {linear}', 'aLinEnv = aEnv')
            if warm:
                body = body.replace('aEnv = transegr:a(0,', f'aEnv = transegr:a(0, {warm}, 0, 0,')
                body = body.replace('aLinEnv = linsegr:a(iVcfEnvStart,',
                                    f'aLinEnv = linsegr:a(0, {warm}, 0, {1/RATE}, iVcfEnvStart,')
                body = body.replace(GATE, f'transegr:a(0, {warm}, 0, 0, .006, -4.2, 1, .006, -4.2, 0)')
            taps = render(body, values, HOLD+warm, native=True)
            index = round(warm*RATE)
            audio = taps[2][index:]
            row = dict(name=name, pre_roll_seconds=warm,
                first10ms_rms=rms(audio[:480]), first50ms_rms=rms(audio[:2400]),
                held_rms=rms(audio[9600:14400]),
                first50ms_mean=sum(audio[:2400])/2400,
                first50ms_peak=max(abs(x) for x in audio[:2400]))
            attacks.append(row)
            traces[name] = taps
            save_csv(DEST/f'{name}.csv', [dict(time=i/RATE, pre_vcf=taps[0][index+i],
                    post_vcf=taps[1][index+i], output=audio[i])
                    for i in range(min(len(audio), int(.05*RATE)))])
            # One fixed audition gain, no per-variant normalization. Each variant
            # is 0.3s held plus 0.2s tail and 0.3s separation; see metadata.json.
            clip = [x*.25 for x in audio[:int(.5*RATE)]]
            clip += [0.0]*(int(.8*RATE)-len(clip))
            audition += clip
            organ_clips[name] = clip
            print(name, row, flush=True)
    save_csv(DEST/'controls.csv', controls)
    save_csv(DEST/'attacks.csv', attacks)
    assert source.read_bytes() == source_bytes, 'fixtures/voice.blue changed during the audit; rerun probes'
    (DEST/'metadata.json').write_text(json.dumps(dict(
        project_sha256=source_hash,
        plugin_sha256=hashlib.sha256((PLUGIN).read_bytes()).hexdigest(),
        rate=RATE, ksmps=32, hold_seconds=HOLD, seed=1234,
        settings=settings, gate_estimate_tau_on=TAU_ON, gate_estimate_tau_off=TAU_OFF,
        audition_order=[v[0] for v in variants], audition_gain=.25,
        organ_comparison_order=[f'organ_{n}_{v}' for n in (14,15,16)
            for v in ('current','circuit_RC','shared_ENV','aligned_gate')]),indent=2)+'\n')
    focused = [x for n in (14,15,16)
               for v in ('current','circuit_RC','shared_ENV','aligned_gate')
               for x in organ_clips[f'organ_{n}_{v}']]
    for name, audio in [('attack_comparison',audition),('organ_comparison',focused)]:
        with wave.open(str(DEST/f'{name}.wav'),'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(3)
            stream.setframerate(RATE)
            stream.writeframes(b''.join(int(max(-1,min(.999999,x))*8388607).to_bytes(
                3,'little',signed=True) for x in audio))
    print(f'PASS: finite control/attack renders; audit artifacts in {DEST}')


if __name__ == '__main__':
    main()
