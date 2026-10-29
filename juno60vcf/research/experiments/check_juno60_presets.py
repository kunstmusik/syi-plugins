#!/usr/bin/env python3
"""Audit every saved patch, its dropdown references and the Roland factory table."""
from research_paths import RESULTS
import argparse
import csv
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
FIELDS = dict(lfo_rate='LFO Rate', lfo_delay_time='LFO Delay',
    lfo_trigger_mode='LFO Trigger', dco_lfo='DCO Lfo', dco_pwm='DCO PWM',
    dco_pwm_source='DCO Lfo Mod', dco_pulse_enabled='DCO Pulse',
    dco_saw_enabled='DCO Saw', dco_sub_enabled='DCO Sub Enabled',
    dco_sub='DCO Sub', dco_noise='DCO Noise', hpf_mode='HPF',
    vcf_freq='VCF Freq', vcf_res='VCF Res', vcf_invert='VCF Dir',
    vcf_env='VCF Env', vcf_lfo='VCF LFO', vcf_kybd='VCF Key',
    vca_mode='VCA Dir', vca_level_adjust='VCA Value', env_attack='ENV Attack',
    env_decay='ENV Decay', env_sustain='ENV Sustain', env_release='ENV Release',
    chorus_mode='Chorus')
SWITCHES = dict(lfo_trigger_mode={'A':0,'M':1},
    dco_pwm_source={'L':0,'M':1,'E':2}, vcf_invert={'N':0,'I':1},
    vca_mode={'E':0,'G':1})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, default=RESULTS / 'juno60_preset_audit.csv')
    args = parser.parse_args()
    root = ET.parse(PROJECT/'fixtures/voice.blue').getroot()
    with (PROJECT/'experiments/juno60_factory_reference.csv').open() as stream:
        reference = {int(row['Number']):row for row in csv.DictReader(stream)}
    rows, factory_numbers = [], set()
    for assignment in root.findall('.//instrumentAssignment'):
        instrument = assignment.find('instrument')
        curves = {name:[float(v) for v in re.search(r'^iJno60'+name+r'\[\] fillarray (.*)$',
            instrument.findtext('alwaysOnInstrumentText'),re.M).group(1).split(',')]
            for name in ('Rates','Delays','Fades')}
        def mapped(name, position):
            x = min(max(position/2.5,0),4)
            index = min(int(x),3)
            lo,hi = curves[name][index:index+2]
            return lo*(hi/lo)**(x-index) if name=='Rates' else lo+(hi-lo)*(x-index)
        assert 'kPitchCents = (225*.06/4.4) * (log(1+exp((kPitchVoltage-.6)/.06)) - log(1+exp(-10)))' in instrument.findtext('instrumentText')
        assert 'kLfoModOct = (3.46*.06/4.4) * (log(1+exp((kLfoVoltage-.6)/.06)) - log(1+exp(-10)))' in instrument.findtext('instrumentText')
        widgets = {w.findtext('objectName'):w for w in instrument.findall('.//bsbObject') if w.findtext('objectName')}
        parameters = {p.get('name'):p for p in instrument.findall('parameterList/parameter')}
        dropdowns = {key:{'id:'+item.get('uniqueId'):(index,item.findtext('name'))
            for index,item in enumerate(w.findall('bsbDropdownItemList/bsbDropdownItem'))}
            for key,w in widgets.items() if w.findall('bsbDropdownItemList/bsbDropdownItem')}
        ids, resolved = set(), {}
        for group in instrument.findall('.//presetGroup'):
            for preset in group.findall('preset'):
                name = preset.get('name')
                assert preset.get('uniqueId') not in ids, (name,'duplicate preset ID')
                ids.add(preset.get('uniqueId'))
                settings = preset.findall('setting')
                assert len(settings)==len({s.get('name') for s in settings}), (name,'duplicate setting')
                assert {s.get('name') for s in settings}==set(parameters), (name,'incomplete/unknown controls')
                values, labels = {}, {}
                for entry in settings:
                    key,value = entry.get('name'),entry.text
                    if key in dropdowns:
                        assert value in dropdowns[key], (assignment.get('arrangementId'),name,key,value,'dangling ID')
                        value,labels[key] = dropdowns[key][value]
                    value = float({'true':'1','false':'0'}.get(value,value))
                    p = parameters[key]
                    assert math.isfinite(value) and float(p.get('min'))<=value<=float(p.get('max')), (name,key,value)
                    values[key] = value
                resolved[preset.get('uniqueId')] = values
                if group.get('name')=='Factory':
                    number = int(name.split()[0])
                    assert number not in factory_numbers
                    factory_numbers.add(number)
                    expected = reference[number]
                    for key,column in FIELDS.items():
                        value = expected[column]
                        value = SWITCHES[key][value] if key in SWITCHES else float(value)
                        assert values[key]==value, (name,key,value,values[key])
                    assert values['lfo_trig']==0, (name,'factory manual trigger must be released')
                    assert values['dco_noise_enabled']==(float(expected['DCO Noise'])>0), name
                position = values['lfo_delay_time']
                rows.append(dict(synth=assignment.get('arrangementId'),group=group.get('name'),name=name,
                    trigger=labels['lfo_trigger_mode'],delay_slider=position,
                    rate_hz=mapped('Rates',values['lfo_rate']),
                    auto_delay_seconds=mapped('Delays',position),auto_fade_seconds=mapped('Fades',position),
                    pitch_depth_cents=225*.06/4.4*(math.log1p(math.exp((values['dco_lfo']/2-.6)/.06))-math.log1p(math.exp(-10))),
                    filter_depth_octaves=3.46*.06/4.4*(math.log1p(math.exp((values['vcf_lfo']/2-.6)/.06))-math.log1p(math.exp(-10))),
                    manual_trigger=values['lfo_trig'],pwm_source=labels['dco_pwm_source'],
                    pwm_slider=values['dco_pwm'],pulse_enabled=values['dco_pulse_enabled'],
                    vca=labels['vca_mode'],chorus=labels['chorus_mode'],factory_match=group.get('name')=='Factory'))
        for key,p in parameters.items():
            widget = widgets[key]
            value = widget.findtext('selectedIndex') if key in dropdowns else widget.findtext('selected')
            if value is None: value = widget.findtext('value')
            value = float({'true':'1','false':'0'}.get(value,value))
            assert abs(value-float(p.get('value')))<1e-9, (assignment.get('arrangementId'),key,'widget/parameter mismatch')
        group = instrument.find('presetGroup')
        selected = group.get('currentPresetUniqueId')
        if selected:
            assert selected in resolved, 'dangling current preset ID'
            modified = any(abs(float(parameters[k].get('value'))-v)>1e-9 for k,v in resolved[selected].items())
            assert not modified or group.get('currentPresetModified')=='true', (assignment.get('arrangementId'),'edited panel marked unmodified')
    assert factory_numbers==set(reference) and len(factory_numbers)==56
    assert len(rows)==116, len(rows)
    with args.csv.open('w',newline='') as stream:
        writer = csv.DictWriter(stream, rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f'PASS: {len(rows)} saved presets, complete/ranged controls, valid dropdown IDs and panel state')
    print('PASS: all 56 factory patches / 1,512 settings match the transcribed Roland table')
    print(f'Per-patch modulation audit: {args.csv}')


if __name__=='__main__':
    main()
