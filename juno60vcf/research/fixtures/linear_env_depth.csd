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
 * Reduced Juno-60 VCF model: four buffered OTA/240 pF stages and a
 * saturating BA662-style resonance path, discretized with TPT.
 *
 * Independent mathematical implementation; no KR-106 source was used.
 * Circuit reference: Roland JUNO-60 Service Notes, CPU board, printed p.9.
 * https://medias.audiofanzine.com/files/roland-juno-60-service-notes-472222.pdf
 * TPT/implicit feedback: Vadim Zavalishin, "Preserving the LTI system
 * topology in s- to z-plane transforms" (2008).
 * https://www.native-instruments.de/fileadmin/redaktion_upload/pdf/KeepTopology.pdf
 * OTA differential-pair law: iOut = iBias * tanh(vDiff / (2 * vThermal)).
 * Bogason/Werner, DAFx-17, section 2.1:
 * https://www.dafx.de/paper-archive/2017/papers/DAFx17_paper_89.pdf
 *
 * Each stage has C * dy/dt = gm * (input - y), hence wc = gm/C.
 * Trapezoidal integration gives y = G*input + (1-G)*z, zNext = 2*y-z,
 * with g = tan(pi*cutoff/sr) and G = g/(1+g). For the four-stage cascade,
 * y = G^4*u + S. The BA662 mixes driven input x with output feedback:
 * u = x - feedback*level*tanh((y - c*x)/level).
 * c = (1.5/48.5) / ((68/10)*(1.5/101.5)) from R1/R2/R3/R5/R24
 * and the 68k stage feedback resistors, neglecting OTA input loading.
 * Solve for d = y - c*x in the current sample; no added unit delay or
 * output clipping. See ../FILTER_RESEARCH.md for the normalized derivation.
 *
 * ideal buffers and linear filter-stage OTAs; add stage saturation
 * and loading only when hardware distortion measurements justify them.
 * Pulse +/-1 and maximum self-oscillation share a nominal 2-unit p-p target,
 * representing Roland's 4 Vp-p TP4 calibration at fixed maximum VCA gain.
 * For K=4.2, the tanh fundamental satisfies N(A/L)=4/K at A/L=0.4509253714;
 * L=2.217661865 therefore gives A=1. This is a relative calibration of the
 * reduced model; K=4.2, source switching and stage loading remain approximate.
 * Input-to-BA662 feedforward gives partial resonance compensation; both
 * signals share the same OTA saturation. Drive precedes both input paths.
 * At resonance zero this reduced model is linear at every drive setting.
 *
 * Uses 4x native sinc oversampling, which adds converter latency. Cutoff
 * is limited below the internal Nyquist frequency. Each UDO instance owns
 * its state; reuse an instance to retain oscillation across gated notes.
 * Warm start is the default: initialize an unexcited self-oscillating core
 * at an approximate settled limit cycle, rather than zero. No hidden preroll.
 * The phase is an output zero crossing; below onset, state remains zero.
 * Cold start is optional for measurements. With noise disabled it stays silent.
 * Optional resistor-noise experiment: R1||R3 and R2||R5 contribute
 * differential-input density sqrt(4*kBoltzmann*T*(Rminus+Rplus)).
 * At 25 C this is about 6.95 nV/sqrt(Hz). Noise enters the BA662 law,
 * not the DCO mixer. Since level = 2*VT/(beta*voltsPerFS), its normalized
 * RMS is level*sqrt(4*k*T*R*local_sr/2)/(2*VT). This preserves density
 * across sample rates. VT=k*T/q. Source impedances/buffers are ideal;
 * OTA, buffer, filter-stage noise and offsets are still omitted. This is
 * one calculated contribution, not a complete hardware noise calibration.
 * https://www.ti.com/document-viewer/lit/html/SBOA345/GUID-F87CE11A-8998-4FB4-BEA6-8D520E81351E
 * Convert k-rate resonance/drive to audio with interp() at the call site,
 * before oversampling, to keep control and input converter latency aligned.
 *
 * @param aIn Input audio, with 0dbfs = 1
 * @param aCutoff Audio-rate cutoff in Hz, clamped to 0.1 .. 0.49*internal_sr
 * @param aResonance Normalized panel position 0..1 (small-signal onset ~0.952)
 * @param aDrive Input gain, >=0; 1 is unity
 * @param iFeedbackScale Multiplier for OTA saturation level (optional, default 1)
 * @param iThermalNoise Enable BA662 resistor-noise experiment (optional, default 0)
 * @param iWarmStart Assume warm self-oscillating state (optional, default 1; 0=cold)
 * @return aOut Four-pole lowpass output, before any VCA or HPF
 */
opcode juno60_filter(aIn, aCutoff, aResonance, aDrive, iFeedbackScale:p, iThermalNoise:o, iWarmStart:p):a
  oversample(4, 1, 1)

  iMaxCutoff = 0.49 * sr
  iLevel = 2.217661865 * max(iFeedbackScale, 0.000001) * 0dbfs
  iCompensation = (1.5/48.5) / ((68/10)*(1.5/101.5))
  if iThermalNoise != 0 then
    iTemperature = 298.15
    iBoltzmann = 1.380649e-23
    iCharge = 1.602176634e-19
    iThermalVoltage = iBoltzmann*iTemperature/iCharge
    iResistance = 1500*100000/(1500+100000) + 1500*47000/(1500+47000)
    iNoiseRms = iLevel * sqrt(4*iBoltzmann*iTemperature*iResistance*sr/2) /
                (2*iThermalVoltage)
    aThermalNoise = gauss:a(0, iNoiseRms)
  else
    aThermalNoise = 0
  endif
  aOut init 0
  kZ1 init 0
  kZ2 init 0
  kZ3 init 0
  kZ4 init 0
  kLastCutoff init -1
  kG init 0
  kB init 0
  kG2 init 0
  kG3 init 0
  kG4 init 0
  ; Let the sinc input converter's initial control step settle before deciding
  ; whether to initialize oscillation. 128 caller samples (~2.7 ms at 48 kHz)
  ; prevent startup ringing from mistaking a below-onset setting for resonance.
  ; This is only a control guard: no filter pre-roll or extra DSP is performed.
  kWarmWait init 512

  kWarmFeedback = 4.2 * limit(aResonance[ksmps-1], 0, 1)
  kIndex = 0
  while kIndex < ksmps do
    kFeedback = 4.2 * limit(aResonance[kIndex], 0, 1)
    kInputGain = max(aDrive[kIndex], 0)
    kCutoff = limit(aCutoff[kIndex], 0.1, iMaxCutoff)
    if kCutoff != kLastCutoff then
      kWarp = tan($M_PI * kCutoff / sr)
      kG = kWarp / (1 + kWarp)
      kB = 1 - kG
      kG2 = kG * kG
      kG3 = kG2 * kG
      kG4 = kG2 * kG2
      kLastCutoff = kCutoff
    endif

    kWarmWait = max(0, kWarmWait-1)
    if iWarmStart != 0 && kWarmWait == 0 && kFeedback > 4 && kWarmFeedback > 4 && kZ1 == 0 && kZ2 == 0 && kZ3 == 0 && kZ4 == 0 then
      ; Harmonic balance of the tanh feedback: K*N(A/level)=4.
      ; N(a)=1-a^2/4+a^4/12-17*a^6/576+O(a^8); a<0.46 at K<=4.2.
      ; Match the four pole phases at an output zero crossing. Three Newton
      ; steps and four assignments replace a long per-note pre-roll.
      kWarmTarget = max(kFeedback, kWarmFeedback)
      kWarmPower = 4*(1-4/kWarmTarget)
      kWarmIteration = 0
      while kWarmIteration < 3 do
        kWarmError = 1-kWarmPower/4+kWarmPower*kWarmPower/12 -
                     17*kWarmPower*kWarmPower*kWarmPower/576-4/kWarmTarget
        kWarmSlope = -0.25+kWarmPower/6-17*kWarmPower*kWarmPower/192
        kWarmPower -= kWarmError/kWarmSlope
        kWarmIteration += 1
      od
      kWarmAmplitude = iLevel*sqrt(max(0, kWarmPower))
      kZ1 = 2*kWarmAmplitude*(1+kWarp)
      kZ2 = 2*kWarmAmplitude
      kZ3 = kWarmAmplitude*(1-kWarp)
      kZ4 = -kWarp*kWarmAmplitude
    endif

    kInput = aIn[kIndex] * kInputGain
    kState = kB * (kG3*kZ1 + kG2*kZ2 + kG*kZ3 + kZ4)
    kRhs = kG4*kInput + kState - iCompensation*kInput + aThermalNoise[kIndex]

    ; d = y - c*x + eta; eta is optional differential-input resistor noise.
    ; Solve d + G^4*feedback*level*tanh(d/level) = rhs.
    ; The derivative is >=1. The unique root lies between 0 and rhs.
    ; Safeguarded Newton steps stay in that bracket even at large drive.
    kLo = min(0, kRhs)
    kHi = max(0, kRhs)
    kDifference = kRhs / (1 + kG4*kFeedback)
    kIteration = 0
    while kIteration < 12 do
      kTanh = tanh(kDifference / iLevel)
      kError = kDifference + kG4*kFeedback*iLevel*kTanh - kRhs
      if abs(kError) <= 1e-12 * (1 + abs(kRhs)) then
        kIteration = 12
      else
        if kError < 0 then
          kLo = kDifference
        else
          kHi = kDifference
        endif
        kSlope = 1 + kG4*kFeedback*(1 - kTanh*kTanh)
        kNext = kDifference - kError/kSlope
        if kNext <= kLo || kNext >= kHi then
          kNext = 0.5 * (kLo + kHi)
        endif
        kDifference = kNext
        kIteration += 1
      endif
    od

    kU = kInput - kFeedback*iLevel*tanh(kDifference / iLevel)
    kY1 = kG*kU + kB*kZ1
    kY2 = kG*kY1 + kB*kZ2
    kY3 = kG*kY2 + kB*kZ3
    kY4 = kG*kY3 + kB*kZ4
    kZ1 = 2*kY1 - kZ1
    kZ2 = 2*kY2 - kZ2
    kZ3 = 2*kY3 - kZ3
    kZ4 = 2*kY4 - kZ4
    aOut[kIndex] = kY4
    kIndex += 1
  od
  xout aOut
endop

/**
 * Four separate listening examples; the output envelope is a VCA after
 * the filter, so the source and filter state continue during the fade.
 *
 * @param p4 Sweep selection: 0=cutoff, 1=resonance, 2=drive, 3=self-oscillation
 */
instr FilterSweep
  aSource = vco2(0.15, 110)
  kResonance = 0.55
  kDrive = 1

  if p4 == 0 then
    prints("Cutoff: 80 -> 30000 -> 80 Hz; resonance 0.55, drive 1\n")
    aCutoff = expseg:a(80, p3/2, 30000, p3/2, 80)
  elseif p4 == 1 then
    prints("Resonance: 0 -> 1 -> 0; cutoff 900 Hz, drive 1\n")
    aCutoff = 900
    kResonance = linseg:k(0, p3/2, 1, p3/2, 0)
  elseif p4 == 2 then
    prints("Drive: 0.25 -> 8 -> 0.25; cutoff 700 Hz, resonance 0.8\n")
    aCutoff = 700
    kResonance = 0.8
    kDrive = expseg:k(0.25, p3/2, 8, p3/2, 0.25)
  else
    prints("Self-oscillation: warm filter, no external excitation; cutoff 248 -> 3968 -> 248 Hz\n")
    aSource = 0
    aCutoff = expseg:a(248, p3/2, 3968, p3/2, 248)
    kResonance = 1
  endif

  aResonance = interp(kResonance)
  aDrive = interp(kDrive)
  aFiltered = juno60_filter(aSource, aCutoff, aResonance, aDrive)
  aVca = linen:a(0.35, 0.02, p3, 0.05)
  aOut = aFiltered * aVca
  out(aOut, aOut)
endin


/**
 * Factory 74/78 startup experiment, independent of 01.blue.
 * Printed settings: Roland JUNO-60 owner's manual p.28 (PDF p.30).
 * Every DCO and panel-noise source is OFF; resonance is maximum.
 * The 20 ms test burst is external laboratory excitation, not a claim
 * about hardware noise. In mode 2 it ends before the VCA opens.
 *
 * p4 = 74 or 78; p5 = 0:exact zero, 1:cold burst, 2:pre-running burst,
 *                       3:cold resistor noise, 4:pre-running resistor noise
 *                       5:default warm state, no noise or pre-roll
 * p6 = burst gain in dBFS; p7 = time before VCA opens (seconds)
 * p8 = key hold time; p9 = MIDI note
 * p3 must include p7 + p8 + envelope release + a short silent tail.
 */
instr FactoryPatch
  iPatch = p4
  iMode = p5
  iWarm = max(0, p7)
  iHold = p8
  iNote = p9
  if iPatch == 74 then
    iFreqPanel = 3.5
    iEnvPanel = 0
    iLfoPanel = 2
    iLfoRatePanel = 5.5
    iLfoDelayPanel = 4
    iDecayPanel = 4
    iSustain = 0.55
    iReleasePanel = 7
    iVcaPanel = 5
  elseif iPatch == 78 then
    iFreqPanel = 2
    iEnvPanel = 4
    iLfoPanel = 0
    iLfoRatePanel = 0
    iLfoDelayPanel = 0
    iDecayPanel = 5
    iSustain = 0
    iReleasePanel = 6
    iVcaPanel = 1
  else
    prints("FactoryPatch: choose 74 or 78\n")
    exitnow(1)
  endif
  prints("Factory %d: mode %d (0=zero, 1=cold burst, 2=warm burst, 3=cold noise, 4=warm noise, 5=warm default), VCA opens at %.1f s\n", iPatch, iMode, iWarm)
  iAttack = 0.001
  iDecay = 0.002 + 11.998 * pow(iDecayPanel/10, 3)
  iRelease = 0.002 + 11.998 * pow(iReleasePanel/10, 3)
  ; Panel LEVEL is -5..+5; maximum is our unity output reference.
  ; The 2.4 dB/unit slope remains provisional pending original-H2 measurements.
  iVcaGain = ampdbfs((iVcaPanel - 5) * 2.4)
  iLfoDelay = (iLfoDelayPanel == 0 ? 0 : 0.001*pow(2000, iLfoDelayPanel/10))
  kLfo = lfo:k(1, 0.3*pow(20/0.3, iLfoRatePanel/10), 1)
  kTime = timeinsts() - iWarm
  kDelay = (iLfoDelay == 0 ? 1 : limit(kTime/iLfoDelay, 0, 1))

  aElapsed = linseg:a(0, p3, p3)
  aNoteTime = aElapsed - iWarm
  aHeldTime = min(aNoteTime, a(iHold))
  aAttackPhase = limit(aHeldTime/iAttack, 0, 1)
  aDecayPhase = limit((aHeldTime-iAttack)/iDecay, 0, 1)
  aReleasePhase = limit((aNoteTime-iHold)/iRelease, 0, 1)
  ; Hardware PWM captures support a -1 raw Attack curve; D/R remain provisional.
  aAttackCurve = (1-exp(-aAttackPhase))/(1-exp(-1))
  aDecayCurve = (1-exp(-4.2*aDecayPhase))/(1-exp(-4.2))
  aReleaseCurve = (1-exp(-4.2*aReleasePhase))/(1-exp(-4.2))
  aEnv = aAttackCurve * (1+(iSustain-1)*aDecayCurve) * (1-aReleaseCurve)
  ; One provisional IR3R01 envelope feeds VCF and the conditioned VCA.
  ; Minimum Attack still rises from zero; no peak-at-keydown bypass.
  aVcfEnv = aEnv
  kBase = (iFreqPanel/10)*16.6667 + octcps(cpsmidinn(iNote))-8
  aCutoff = 7.8*exp(0.6931472*limit(kBase +
                  aVcfEnv*(iEnvPanel/10)*12 + kLfo*kDelay*(iLfoPanel/10)*3, -10, 14))

  iBurstStart = (iMode == 2 ? 0 : iWarm)
  aBurstGate = limit((aElapsed-iBurstStart)*sr, 0, 1) *
               limit((iBurstStart+0.02-aElapsed)*sr, 0, 1)
  aTestInput = random:a(-1, 1) * ampdbfs(p6) * aBurstGate
  if iMode == 0 || iMode >= 3 then
    aTestInput = 0
  endif
  iThermalNoise = (iMode == 3 || iMode == 4 ? 1 : 0)
  iWarmStart = (iMode == 5 ? 1 : 0)
  aResonance = 1
  aDrive = 1
  aFiltered = juno60_filter(aTestInput, aCutoff, aResonance, aDrive, 1, iThermalNoise, iWarmStart)
  ; Common HPF is downstream of the envelope VCA. Factory 74 uses HPF 1;
  ; factory 78 uses flat HPF 0. Patch LEVEL follows the HPF.
  ; Reduced ENV branch of C9/R43/R44/R45; direct feedthrough is 12/49.
  aEnvPole = tone(aEnv, sr/(6.283185307179586)*cosinv(2-cosh(1/(sr*.01078))))
  aVcaControl = (12/49)*aEnv + (37/49)*aEnvPole
  ; 4x medium sinc has a settled delay of 94 caller samples.
  aVoices = aFiltered * delay(aVcaControl, 94/sr)
  if iPatch == 74 then
    aVoices = zdf1pole(aVoices, 234.61384554, 1)
  endif
  aOut = aVoices * iVcaGain
#ifdef STARTUP_TAPS
  ; Measurement only: raw filter left, gated output right.
  out(aFiltered, aOut)
#else
  out(aOut, aOut)
#endif
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
  aCutoff = iCutoff
  aResonance = iResonance
  aDrive = 1
  aFiltered = juno60_filter(aInput, aCutoff, aResonance, aDrive)
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
; Matched levels: csound --smacro:LEVEL_REFERENCES=1 Juno60Filter.csd
#ifdef LEVEL_REFERENCES
i "LevelReference"  0    2  0 0 10 ; pulse, open filter
i "LevelReference"  2.5  2  3 0 10 ; autonomous resonance, flat HPF
i "LevelReference"  5    2  2 0 10 ; noise maximum
i "LevelReference"  7.5  2  2 0 2  ; loaded noise control at 2/10
i "LevelReference" 10    2  3 1 10 ; resonance through HPF 1
i "LevelReference" 12.5  2  3 2 10 ; resonance through HPF 2
i "LevelReference" 15    2  3 3 10 ; resonance through HPF 3
#else

; Factory startup A/B: csound --smacro:FACTORY_STARTUP=1 Juno60Filter.csd
; Warm default, with every DCO OFF: no added noise or timed pre-roll.
#ifdef FACTORY_STARTUP
i "FactoryPatch"  0    7  74 5 -120 0 1.5 60
i "FactoryPatch"  7.5  5  78 5 -120 0 1.5 60
#else
; Play:   csound Juno60Filter.csd
; Render: csound -W -f -o Juno60Filter.wav Juno60Filter.csd
i "FilterSweep"  0    8  0
i "FilterSweep"  8.5  8  1
i "FilterSweep" 17    8  2
i "FilterSweep" 25.5  8  3
#endif
#endif
e
</CsScore>
</CsoundSynthesizer>
