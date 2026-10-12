<CsoundSynthesizer>
<CsOptions>
-odac -d -m0
</CsOptions>
<CsInstruments>
sr = 48000
ksmps = 32
nchnls = 2
0dbfs = 1

/**
 * Native filter parameter sweeps, using internal 4x sinc oversampling.
 * @param p4 Sweep: 0=cutoff, 1=resonance, 2=drive, 3=self-oscillation
 */
instr FilterSweep
  aSource = vco2(0.15, 110)
  kResonance = 0.55
  kDrive = 1
  if p4 == 0 then
    aCutoff = expseg:a(80, p3/2, 30000, p3/2, 80)
  elseif p4 == 1 then
    aCutoff = 900
    kResonance = linseg:k(0, p3/2, 1, p3/2, 0)
  elseif p4 == 2 then
    aCutoff = 700
    kResonance = 0.8
    kDrive = expseg:k(0.25, p3/2, 8, p3/2, 0.25)
  else
    aSource = 0
    aCutoff = expseg:a(248, p3/2, 3968, p3/2, 248)
    kResonance = 1
  endif
  aFiltered = juno60vcf(aSource, aCutoff, kResonance, kDrive)
  aOut = aFiltered * linen:a(0.35, 0.02, p3, 0.05)
  out(aOut, aOut)
endin
/**
 * Matched electrical level references, with an output listening gain of 0.2.
 * HPF and LEVEL follow the envelope VCA. No chorus or extra excitation.
 * @param p4 Source: 0=pulse, 1=saw, 2=noise, 3=VCF self-oscillation
 * @param p5 HPF: 0=flat, 1/2/3=one-pole highpass
 * @param p6 Noise panel position 0..10 (other sources ignore it)
 */
instr LevelReference
  iResonance = (p4 == 3 ? 1 : 0)
  iCutoff = (p4 == 3 ? 248 : 0.49*sr)
  aInput = 0
  if p4 == 0 then
    aInput = vco2(1, cpsmidinn(60), 2, 0.5)
  elseif p4 == 1 then
    aInput = vco2(1, cpsmidinn(60))
  elseif p4 == 2 then
    iPosition = limit(p6/10, 0, 1)
    iNoiseGain = iPosition/(1+(50/47)*iPosition*(1-iPosition))
    aInput = random:a(-1, 1)*iNoiseGain
  endif
  aFiltered = juno60vcf(aInput, iCutoff, iResonance, 1)
  aVoices = aFiltered * linen:a(1, 0.01, p3, 0.02)
  if p5 > 0 then
    iHpfHz = (p5 == 1 ? 234.61384554 : p5 == 2 ? 516.15046019 : 1098.19246849)
    aVoices = zdf1pole(aVoices, iHpfHz, 1)
  endif
  ; Fixed maximum patch LEVEL reference; listening headroom is common.
  aOut = 0.2*aVoices
  out(aOut, aOut)
endin

</CsInstruments>
<CsScore>
; Matched levels: csound --smacro:LEVEL_REFERENCES=1 juno60vcf/examples/Juno60Native.csd
#ifdef LEVEL_REFERENCES
i "LevelReference"  0    2  0 0 10 ; pulse, open filter
i "LevelReference"  2.5  2  3 0 10 ; autonomous resonance, flat HPF
i "LevelReference"  5    2  2 0 10 ; noise maximum
i "LevelReference"  7.5  2  2 0 2  ; loaded noise control at 2/10
i "LevelReference" 10    2  3 1 10 ; resonance through HPF 1
i "LevelReference" 12.5  2  3 2 10 ; resonance through HPF 2
i "LevelReference" 15    2  3 3 10 ; resonance through HPF 3
#else

i "FilterSweep"  0    8  0
i "FilterSweep"  8.5  8  1
i "FilterSweep" 17    8  2
i "FilterSweep" 25.5  8  3
#endif
e
</CsScore>
</CsoundSynthesizer>
