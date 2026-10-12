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
 * output clipping. The resistor ratios above define the normalized compensation.
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
