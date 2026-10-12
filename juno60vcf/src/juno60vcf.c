/*
 * Native port of the independent mathematical model in
 * ../tests/reference/juno60_filter.udo.
 * Four buffered linear OTA stages, TPT integrators, nonlinear OTA feedback.
 * No KR-106 source or Csound filter implementation was copied.
 * Hardware/derivation references and provisional calibration are in that UDO.
 */
#include "csdl.h"
#include <samplerate.h>
#include <math.h>
#include <string.h>

#if CS_VERSION != 7
#error "juno60vcf requires the Csound 7 plugin SDK"
#endif

typedef struct {
    OPDS h;
    cs_float *out, *in, *cutoff, *resonance, *drive, *scale, *oversampling, *warm_start;
    cs_double z[4], last_cutoff, g, b, g2, g3, g4;
    cs_double pi_over_sr, max_cutoff, level, previous[3], warm_feedback;
    int audio[3], control[3], factor;
    SRC_STATE *up, *down;
    AUXCH buffers, src_buffers;
    cs_float *input, *upsampled, *filtered, *output;
    /* libsamplerate's ABI requires float, regardless of Csound precision. */
    float *src_input, *src_output;
} JUNO60VCF;

/* R1/R2=1.5k, R3=100k, R5=47k, R24=10k, stage feedback=68k.
   Normalize out the 6.8 input gain; see ../tests/reference/juno60_filter.udo. */
static const cs_double input_compensation =
    (1.5 / 48.5) / ((68.0 / 10.0) * (1.5 / 101.5));

static cs_double clamp(cs_double value, cs_double lo, cs_double hi)
{
    return fmin(hi, fmax(lo, value));
}

static cs_double filter_sample(JUNO60VCF *p, cs_double input, cs_double cutoff,
                            cs_double resonance, cs_double drive)
{
    cutoff = clamp(cutoff, 0.1, p->max_cutoff);
    if (cutoff != p->last_cutoff) {
        cs_double warp = tan(p->pi_over_sr * cutoff);
        p->g = warp / (1.0 + warp);
        p->b = 1.0 - p->g;
        p->g2 = p->g * p->g;
        p->g3 = p->g2 * p->g;
        p->g4 = p->g2 * p->g2;
        p->last_cutoff = cutoff;
    }
    cs_double feedback = 4.2 * clamp(resonance, 0.0, 1.0);
    if (*p->warm_start != 0.0 && feedback > 4.0 && p->warm_feedback > 4.0 &&
        p->z[0] == 0.0 && p->z[1] == 0.0 && p->z[2] == 0.0 && p->z[3] == 0.0) {
        /* Warm, autonomous limit-cycle approximation, at an output zero crossing.
           For a=A/L, the tanh fundamental gain is
           N(a)=1-a^2/4+a^4/12-17*a^6/576+O(a^8). Solve K*N(a)=4.
           K <= 4.2 keeps a < 0.46; three Newton steps suffice. No preroll.
           Use the original block target, not the sinc startup overshoot. */
        cs_double target = p->warm_feedback;
        cs_double power = 4.0 * (1.0 - 4.0 / target);
        for (int i = 0; i < 3; ++i) {
            cs_double error = 1.0 - power/4.0 + power*power/12.0
                           - 17.0*power*power*power/576.0 - 4.0/target;
            cs_double slope = -0.25 + power/6.0 - 17.0*power*power/192.0;
            power -= error / slope;
        }
        cs_double amplitude = p->level * sqrt(fmax(0.0, power));
        cs_double warp = p->g / p->b;
        p->z[0] = 2.0*amplitude*(1.0 + warp);
        p->z[1] = 2.0*amplitude;
        p->z[2] = amplitude*(1.0 - warp);
        p->z[3] = -warp*amplitude;
    }
    input *= fmax(0.0, drive);
    cs_double state = p->b * (p->g3*p->z[0] + p->g2*p->z[1]
                          + p->g*p->z[2] + p->z[3]);
    cs_double rhs = p->g4 * input + state - input_compensation * input;
    cs_double u = input;
    if (feedback != 0.0) {
        cs_double lo = fmin(0.0, rhs), hi = fmax(0.0, rhs);
        cs_double difference = rhs / (1.0 + p->g4 * feedback);
        cs_double t = 0.0;
        int converged = 0;
        /* Solve d + G^4*K*L*tanh(d/L) = rhs, where d = y - c*input.
           Monotonic; derivative >= 1 and root between 0 and rhs. */
        for (int iteration = 0; iteration < 12; ++iteration) {
            t = tanh(difference / p->level);
            cs_double error = difference + p->g4*feedback*p->level*t - rhs;
            if (fabs(error) <= 1e-12 * (1.0 + fabs(rhs))) {
                converged = 1;
                break;
            }
            if (error < 0.0) lo = difference;
            else hi = difference;
            cs_double slope = 1.0 + p->g4*feedback*(1.0 - t*t);
            cs_double next = difference - error / slope;
            difference = next <= lo || next >= hi ? 0.5*(lo + hi) : next;
        }
        if (!converged) t = tanh(difference / p->level);
        u -= feedback * p->level * t;
    }
    for (int stage = 0; stage < 4; ++stage) {
        cs_double y = p->g*u + p->b*p->z[stage];
        p->z[stage] = 2.0*y - p->z[stage];
        u = y;
    }
    return u;
}

static int32_t juno60vcf_deinit(CSOUND *csound, JUNO60VCF *p)
{
    (void)csound;
    if (p->up) p->up = src_delete(p->up);
    if (p->down) p->down = src_delete(p->down);
    /* AUXCH storage is released by Csound. */
    return OK;
}

static int32_t juno60vcf_init(CSOUND *csound, JUNO60VCF *p)
{
    juno60vcf_deinit(csound, p);
    cs_double factor = *p->oversampling;
    if (factor == 0.0) factor = 4.0;
    if (factor != 1.0 && factor != 2.0 && factor != 4.0)
        return csound->InitError(csound, "juno60vcf: oversampling must be 1, 2 or 4");
    if (!isfinite(*p->scale))
        return csound->InitError(csound, "juno60vcf: feedback scale must be finite");
    if (*p->warm_start != 0.0 && *p->warm_start != 1.0)
        return csound->InitError(csound, "juno60vcf: warm start must be 0 or 1");
    p->factor = (int)factor;
    /* Guard the TPT tangent at the processing rate, before downsampling. */
    p->max_cutoff = 0.49 * GetLocalSr(&p->h) * factor;
    p->pi_over_sr = 3.14159265358979323846 / (GetLocalSr(&p->h) * factor);
    /* Roland TP4: pulse and maximum self-oscillation both 4 Vp-p.
       +/-1 pulse defines our 2-unit p-p reference. At K=4.2, independent
       tanh harmonic balance gives A/L=0.4509253714. See the CSD derivation. */
    p->level = 2.217661865 * fmax(*p->scale, 0.000001) * csound->Get0dBFS(csound);
    p->last_cutoff = -1.0;
    memset(p->z, 0, sizeof(p->z));
    cs_float *args[] = {p->cutoff, p->resonance, p->drive};
    for (int i = 0; i < 3; ++i) {
        p->audio[i] = IS_ASIG_ARG(args[i]);
        p->control[i] = IS_KSIG_ARG(args[i]);
        p->previous[i] = *args[i];
    }
    if (p->factor == 1) return OK;

    uint32_t n = GetLocalKsmps(&p->h);
    size_t count = (size_t)n * (5 + 5*p->factor);
    csound->AuxAlloc(csound, count * sizeof(cs_float), &p->buffers);
    size_t src_count = (size_t)n * (4 + 4*p->factor);
    csound->AuxAlloc(csound, src_count * sizeof(float), &p->src_buffers);
    if (!p->buffers.auxp || !p->src_buffers.auxp)
        return csound->InitError(csound, "juno60vcf: buffer allocation failed");
    p->input = (cs_float *)p->buffers.auxp;
    p->upsampled = p->input + 4*n;
    p->filtered = p->upsampled + 4*n*p->factor;
    p->output = p->filtered + n*p->factor;
    p->src_input = (float *)p->src_buffers.auxp;
    p->src_output = p->src_input + 4*n;
    int error = 0;
    /* One interleaved converter keeps all four input signals aligned. */
    p->up = src_new(SRC_SINC_MEDIUM_QUALITY, 4, &error);
    if (p->up) p->down = src_new(SRC_SINC_MEDIUM_QUALITY, 1, &error);
    if (!p->up || !p->down) {
        juno60vcf_deinit(csound, p);
        return csound->InitError(csound, "juno60vcf: SRC initialization: %s",
                                 src_strerror(error));
    }
    /* Prime both converters with silence: continuous, block-size-independent
       startup latency, and no discarded input or stale partial output blocks. */
    /* These temporary buffers also belong to the libsamplerate boundary. */
    float zeros[256*4] = {0};
    float discard[256*4*4];
    SRC_DATA prime = {0};
    prime.data_in = zeros;
    prime.data_out = discard;
    prime.input_frames = 256;
    prime.output_frames = 256*p->factor;
    prime.src_ratio = p->factor;
    error = src_process(p->up, &prime);
    if (!error) {
        prime.input_frames = 256*p->factor;
        prime.output_frames = 256;
        prime.src_ratio = 1.0/p->factor;
        error = src_process(p->down, &prime);
    }
    if (error) {
        juno60vcf_deinit(csound, p);
        return csound->InitError(csound, "juno60vcf: SRC priming: %s",
                                 src_strerror(error));
    }
    return OK;
}

static int32_t convert(CSOUND *csound, JUNO60VCF *p, SRC_STATE *converter,
                       const cs_float *in, cs_float *out, long in_frames,
                       long out_frames, int channels, cs_double ratio)
{
    SRC_DATA data = {0};
    for (long i = 0; i < in_frames*channels; ++i)
        p->src_input[i] = (float)in[i];
    data.data_in = p->src_input;
    data.data_out = p->src_output;
    data.input_frames = in_frames;
    data.output_frames = out_frames;
    data.src_ratio = ratio;
    int error = src_process(converter, &data);
    if (error)
        return csound->PerfError(csound, &p->h, "juno60vcf: SRC: %s",
                                 src_strerror(error));
    if (data.input_frames_used != in_frames || data.output_frames_gen != out_frames)
        return csound->PerfError(csound, &p->h, "juno60vcf: incomplete SRC block");
    for (long i = 0; i < out_frames*channels; ++i)
        out[i] = (cs_float)p->src_output[i];
    return OK;
}

static int32_t juno60vcf_perf(CSOUND *csound, JUNO60VCF *p)
{
    uint32_t n = GetLocalKsmps(&p->h);
    uint32_t offset = GetKsmpsOffset(&p->h), end = n - GetEarlySmps(&p->h);
    cs_float *args[] = {p->cutoff, p->resonance, p->drive};
    cs_double steps[3];
    cs_double target_resonance = p->audio[1] && end > offset
                              ? p->resonance[end - 1] : *p->resonance;
    p->warm_feedback = 4.2 * clamp(isfinite(target_resonance) ? target_resonance : 0.0,
                                   0.0, 1.0);
    for (int i = 0; i < 3; ++i)
        steps[i] = p->control[i] ? (*args[i] - p->previous[i]) / n : 0.0;

    for (uint32_t frame = 0; frame < n; ++frame) {
        cs_double controls[3];
        for (int i = 0; i < 3; ++i) {
            controls[i] = p->audio[i] ? args[i][frame]
                : p->control[i] ? p->previous[i] + steps[i]*(frame + 1) : *args[i];
            if (!isfinite(controls[i])) controls[i] = 0.0;
        }
        cs_double in = frame >= offset && frame < end ? p->in[frame] : 0.0;
        if (!isfinite(in)) in = 0.0;
        if (p->factor == 1) {
            /* At 1x, do not advance state outside the active sample range. */
            p->out[frame] = frame >= offset && frame < end
                ? (cs_float)filter_sample(p, in, controls[0], controls[1], controls[2])
                : 0;
        } else {
            p->input[4*frame] = (cs_float)in;
            for (int i = 0; i < 3; ++i)
                p->input[4*frame + i + 1] = (cs_float)controls[i];
        }
    }
    for (int i = 0; i < 3; ++i) p->previous[i] = *args[i];
    if (p->factor != 1) {
        long high_frames = (long)n * p->factor;
        int32_t error = convert(csound, p, p->up, p->input, p->upsampled,
                                n, high_frames, 4, p->factor);
        if (error) return error;
        for (long frame = 0; frame < high_frames; ++frame) {
            const cs_float *x = p->upsampled + 4*frame;
            p->filtered[frame] = (cs_float)filter_sample(p, x[0], x[1], x[2], x[3]);
        }
        error = convert(csound, p, p->down, p->filtered, p->output,
                        high_frames, n, 1, 1.0/p->factor);
        if (error) return error;
        for (uint32_t frame = 0; frame < n; ++frame)
            p->out[frame] = frame >= offset && frame < end ? p->output[frame] : 0;
    }
    /* Prevent denormal slowdowns after notes decay to inaudible levels. */
    for (int stage = 0; stage < 4; ++stage)
        if (fabs(p->z[stage]) < 1e-30) p->z[stage] = 0.0;
    return OK;
}

static OENTRY localops[] = {
    {.opname = "juno60vcf", .dsblksiz = sizeof(JUNO60VCF),
     .outypes = "a", .intypes = "axxxpop", .init = (SUBR)juno60vcf_init,
     .perf = (SUBR)juno60vcf_perf, .deinit = (SUBR)juno60vcf_deinit}
};

LINKAGE
