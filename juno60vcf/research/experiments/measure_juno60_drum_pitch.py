#!/usr/bin/env python3
"""Separate drum78 pitch decay, probable key release and native filter tracking.

python3 experiments/measure_juno60_drum_pitch.py captures/public captures/harman
Reproduces the saved pre-driver linear-depth baseline. Candidate fits are
audition experiments, not production calibrations. Requires
existing Csound, ffmpeg, NumPy/SciPy. Uses hardware audio, no emulator code.
"""
from research_paths import RESULTS
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.io import wavfile
from scipy.optimize import least_squares

from analyze_juno60_control_capture import track_frequency
from check_juno60_startup import PLUGIN, render
from measure_juno60_attack_curve import pulse_duty

PROJECT = Path(__file__).resolve().parents[1]
DEST = RESULTS / 'juno60_drum_pitch'
DECAY = .002+11.998*.5**3
LATENCY = 94
# Preserve the exploratory linear-depth comparison from before the driver fix.
BASELINE = PROJECT/'fixtures/linear_env_depth.csd'
ORCHESTRA = BASELINE.read_text().split('<CsInstruments>',1)[1].split('</CsInstruments>',1)[0]


def onset(signal, rate):
    return np.flatnonzero(abs(signal) > .01*np.max(abs(signal)))[0]/rate


def trajectory(signal, rate):
    time, pitch = track_frequency(signal[:round(.195*rate)], rate, 50, 10000)
    return time-onset(signal[:round(.17*rate)], rate), pitch


def falling(time, decay):
    phase = np.clip((time-.001)/decay, 0, 1)
    return (np.exp(-4.2*phase)-np.exp(-4.2))/(1-np.exp(-4.2))


def metrics(time, pitch):
    row = {}
    for label, lo, hi in [('initial',.02,.10), ('later',.11,.145)]:
        keep = (time >= lo) & (time < hi)
        row[label+'_octaves_per_second'] = float(np.polyfit(time[keep],np.log2(pitch[keep]),1)[0])
    early = np.median(pitch[(time >= .02) & (time < .04)])
    late = np.median(pitch[(time >= .10) & (time < .12)])
    row.update(early_hz=float(early), late_hz=float(late),
               fall_octaves=float(np.log2(early/late)))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('public_directory', type=Path)
    parser.add_argument('harman_directory', type=Path)
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((PROJECT/'experiments/juno60_public_recordings.json').read_text())
    entry = next(x for x in manifest['captures'] if x['file']=='synthmania-78-Synthesizer-Drum.mp3')
    source = args.public_directory/entry['file']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == entry['sha256']
    orchestra = ORCHESTRA.replace(
        'aFiltered = juno60_filter(aTestInput, aCutoff, aResonance, aDrive, 1, iThermalNoise, iWarmStart)',
        'aFiltered = juno60vcf(aTestInput, aCutoff, aResonance, aDrive, 1, 4, iWarmStart)')
    rows, traces, clips = [], [], []
    with tempfile.TemporaryDirectory(prefix='juno60-drum-') as temporary:
        directory = Path(temporary)
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-c:a','pcm_f32le',
                        str(directory/'hardware.wav')],check=True)
        rate, audio = wavfile.read(directory/'hardware.wav')
        hardware = audio[:,0].astype(float)
        hw_onset = onset(hardware[:round(.17*rate)],rate)
        ht, hp = trajectory(hardware,rate)
        rows.append(dict(variant='hardware',**metrics(ht,hp)))

        def probe(body, hold):
            raw, gated, actual_rate = render(directory,body,
                f'i "FactoryPatch" 0 3.5 78 5 0 0 {hold} 60',rate,32,native=True)
            assert actual_rate == rate
            return np.asarray(raw), np.asarray(gated)

        _, current = probe(orchestra,.3)
        model_onset = onset(current[:round(.17*rate)],rate)
        mt, mp = trajectory(current,rate)
        rows.append(dict(variant='current_original_tuning_hold_300ms',**metrics(mt,mp)))
        # Audio threshold is not key-on. Use the model's threshold minus its
        # measured SRC delay only as an explicitly stated alignment assumption.
        offset_time = model_onset-LATENCY/rate
        fit_keep = (ht+hw_onset >= .06) & (ht+hw_onset < .145)
        fit_time, fit_pitch = ht[fit_keep]+offset_time, np.log2(hp[fit_keep])
        design = np.column_stack((np.ones(len(fit_time)),falling(fit_time,DECAY)))
        base, depth = np.linalg.lstsq(design,fit_pitch,rcond=None)[0]
        fixed_rate_rmse = float(1200*np.sqrt(np.mean((design @ [base,depth]-fit_pitch)**2)))
        fit = least_squares(lambda v: v[0]+4.8*falling(fit_time,v[1])-fit_pitch,
                            [base,DECAY*4.8/depth], bounds=([0,.5],[16,4]))
        assert fit.success and 3 < depth < 5 and 1.5 < fit.x[1] < 3
        slower_base, slower_decay = fit.x
        slow_rmse = float(1200*np.sqrt(np.mean(fit.fun**2)))
        # octcps uses engine tuning; derive the exact baseline from the tapped
        # control instead of assuming that 7.8*2^FREQ is its final value.
        taps = orchestra.replace('out(aFiltered, aOut)','out(aCutoff, aFiltered)')
        command, filtered = probe(taps,.3)
        ft, fp = track_frequency(filtered[:round(.17*rate)],rate,50,10000)
        keep = (ft >= .025) & (ft < .10)
        requested = np.interp(ft[keep]-LATENCY/rate,np.arange(len(command))/rate,command)
        error = 1200*np.log2(fp[keep]/requested)
        assert abs(np.median(error)) < 1 and np.max(abs(error)) < 2
        # Extrapolate the known ENV from an accurately tracked command sample.
        sample = round(.04*rate)
        key_reference = command[sample]/2**(4.8*falling(np.array([sample/rate]),DECAY)[0])
        current_shift = np.log2(rows[0]['early_hz']/rows[1]['early_hz'])
        candidates = [('current_hold_300ms',4.8,DECAY,current_shift,.3),
                      ('current_hold_105ms',4.8,DECAY,current_shift,.105),
                      ('shallower_env_hold_105ms',float(depth),DECAY,float(base-np.log2(key_reference)),.105),
                      ('slower_decay_hold_105ms',4.8,float(slower_decay),float(slower_base-np.log2(key_reference)),.105)]
        excerpt_samples = round(.15*rate)
        hardware_excerpt = hardware[round(hw_onset*rate):round(hw_onset*rate)+excerpt_samples]
        clips.append(('hardware',hardware_excerpt))
        for label, amount, duration, shift, hold in candidates:
            body = orchestra.replace('iEnvPanel = 4\n',f'iEnvPanel = {amount/1.2:.12g}\n')
            body = body.replace('iDecay = 0.002 + 11.998 * pow(iDecayPanel/10, 3)',f'iDecay = {duration:.12g}')
            body = body.replace('kBase = (iFreqPanel/10)*16.6667 + octcps(cpsmidinn(iNote))-8',
                f'kBase = (iFreqPanel/10)*16.6667 + octcps(cpsmidinn(iNote))-8 + {shift:.12g}')
            _, signal = probe(body,hold)
            time, pitch = trajectory(signal,rate)
            rows.append(dict(variant=label,**metrics(time,pitch)))
            for t, f in zip(time,pitch):
                traces.append(dict(variant=label,seconds_after_audio_onset=float(t),frequency_hz=float(f)))
            begin = round(onset(signal[:round(.17*rate)],rate)*rate)
            clips.append((label,signal[begin:begin+excerpt_samples]))
            # Save full candidate notes and their exact standalone source.
            csd = (directory/'probe.csd').read_text().replace('out(aFiltered, aOut)','out(aOut, aOut)')
            (DEST/f'{label}.csd').write_text(csd)
            gain = .12/np.sqrt(np.mean(signal[begin:begin+round(.10*rate)]**2))
            wavfile.write(DEST/f'{label}.wav',rate,(signal*gain).astype(np.float32))
        for t,f in zip(ht,hp):
            traces.append(dict(variant='hardware',seconds_after_audio_onset=float(t),frequency_hz=float(f)))
        audition = []
        for _, clip in clips:
            clip = clip.copy()
            clip *= .12/np.sqrt(np.mean(clip[:round(.10*rate)]**2))
            # Common 2ms endpoint fades hide excerpt splices, not onset shape.
            fade = round(.002*rate)
            clip[-fade:] *= np.linspace(1,0,fade)
            audition.extend(clip)
            audition.extend(np.zeros(round(.35*rate)))
        audition = np.asarray(audition)
        assert np.max(abs(audition)) < 1
        wavfile.write(DEST/'drum_early_comparison.wav',rate,audition.astype(np.float32))

    # Independent raw ENV decay rate from PWM duty, rather than VCA amplitude.
    duty_manifest = json.loads((PROJECT/'experiments/juno60_attack_curve/captures.json').read_text())
    decay_fits = []
    for name in ('Juno 60 PWM=5.wav','Juno 60 PWM=10.wav','Juno 60 PWM10Sus=0.wav'):
        path = args.harman_directory/name
        item = next(x for x in duty_manifest['captures'] if x['file']==name)
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        sample_rate, raw = wavfile.read(path)
        time,duty = pulse_duty(raw[:,0].astype(float)/2**31,sample_rate)
        peak = time[np.argmax(duty)]
        keep = (time > peak+.02) & (time < peak+.8)
        t,y = time[keep]-peak,duty[keep]
        fit = least_squares(lambda v: v[0]+v[1]*np.exp(-v[2]*t)-y,
                            [.5,float(max(duty)-.5),2.8],bounds=([.4,0,.1],[.8,.5,10]))
        assert fit.success
        decay_fits.append(dict(file=name,source_sha256=item['sha256'],
            lambda_per_second=float(fit.x[2]),duty_rmse=float(np.sqrt(np.mean(fit.fun**2)))))
    for filename,data in [('pitch_metrics.csv',rows),('pitch_traces.csv',traces)]:
        with (DEST/filename).open('w',newline='') as output:
            writer = csv.DictWriter(output,data[0].keys())
            writer.writeheader()
            writer.writerows(data)
    result = dict(source=entry,csd_sha256=hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
        csd_source=str(BASELINE.relative_to(PROJECT)),
        plugin_sha256=hashlib.sha256(PLUGIN.read_bytes()).hexdigest(),
        hardware_audio_onset=hw_onset,model_audio_onset=model_onset,metrics=rows,
        native_command_error_cents=dict(median=float(np.median(error)),p01=float(np.quantile(error,.01)),p99=float(np.quantile(error,.99))),
        raw_pwm_decay_fits=decay_fits,current_lambda_per_second=4.2/DECAY,
        fixed_decay_fit=dict(depth_octaves=float(depth),decay_seconds=DECAY,rmse_cents=fixed_rate_rmse),
        fixed_depth_fit=dict(depth_octaves=4.8,decay_seconds=float(slower_decay),rmse_cents=slow_rmse),
        candidates=[dict(label=a,depth_octaves=b,decay_seconds=c,tuning_shift_octaves=d,hold_seconds=e) for a,b,c,d,e in candidates],
        audition_order=[label for label,_ in clips],slot_seconds=.5,excerpt_seconds=.15,
        audition_gain='Each excerpt scaled to RMS .12 over its first .10s; pitch shifts explicitly recorded. End-only 2ms fade.',
        limitations='Short performance, MP3, unknown note, key-on, key-off and baseline. Fits assume audio-threshold alignment and curve -4.2. Release at .105s is an inference. Neither candidate identifies a unique hardware mapping. No production DSP or preset changes.')
    (DEST/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(metrics=rows,fixed_decay=result['fixed_decay_fit'],fixed_depth=result['fixed_depth_fit'],
                         raw_pwm_decay_fits=decay_fits,native_error=result['native_command_error_cents']),indent=2))
    print(f'PASS: native command tracking and reproducible drum candidates; {DEST}')


if __name__=='__main__':
    main()
