#include "nn_infer.hpp"
#include "weights.hpp"

// Rounding headroom: acc_t is sized for the accumulator, not for acc + half.
typedef ap_int<NN_ACC_W + 2> round_t;

static acc_t requantize(acc_t v, int shift, int lo, int hi) {
    round_t q = v;

    if (shift > 0) {
        const round_t half = round_t(1) << (shift - 1);
        const round_t drop = round_t(v) & ((round_t(1) << shift) - 1);

        // arithmetic shift, floor.
        q = (round_t(v) + half) >> shift;
        if (drop == half && (q & 1) == 1) {
            q -= 1;
        }
    }

    if (q < lo) {
        q = lo;
    } 

    if (q > hi) {
        q = hi;
    }

    return acc_t(q);
}

void nn_infer(const ap_int<8> in[NN_CH * NN_WINDOW], ap_int<32> out[NN_CLASSES]) {
    #pragma HLS INTERFACE m_axi     port=in  offset=slave bundle=gmem 
    #pragma HLS INTERFACE m_axi     port=out offset=slave bundle=gmem 
    #pragma HLS INTERFACE s_axilite port=in     bundle=control
    #pragma HLS INTERFACE s_axilite port=out    bundle=control
    #pragma HLS INTERFACE s_axilite port=return bundle=control

    const int T2 = MAXPOOL_OUT;

    quant_input_t x[NN_CH][NN_WINDOW];
    relu1_t a1[CONV1_OUT][NN_WINDOW], p1[CONV1_OUT][T2];
    relu2_t a2[CONV2_OUT][T2];
    quant_pool_t g[CONV2_OUT];
    relu3_t h[FC1_OUT];

    LOAD_C: for (int c = 0; c < NN_CH; ++c) {
        LOAD_T: for (int t = 0; t < NN_WINDOW; ++t) {
            x[c][t] = quant_input_t(in[c * NN_WINDOW + t]);
        }
    }

    // conv1 -> relu1
    CONV1_O: for (int o = 0; o < CONV1_OUT; ++o) {
        CONV1_T: for (int t = 0; t < NN_WINDOW; ++t) {
            acc_t acc = conv1_b[o];
            CONV1_I: for (int i = 0; i < CONV1_IN; ++i)
                CONV1_TAP: for (int k = 0; k < CONV1_K; ++k) {
                    const int s = t + k - CONV1_PAD_L;
                    if (s >= 0 && s < NN_WINDOW)               // zero padding
                        acc += conv1_w[(o * CONV1_IN + i) * CONV1_K + k] * x[i][s];
                }
            a1[o][t] = requantize(acc, CONV1_SHIFT, CONV1_LO, CONV1_HI);
        }
    }

    // maxpool: no quantizer, so no shift and no clamp — max passes the scale through
    MAXPOOL_O: for (int o = 0; o < CONV1_OUT; ++o) {
        MAXPOOL_T: for (int t = 0; t < T2; ++t) {
            relu1_t m = a1[o][t * MAXPOOL_STRIDE];
            MAXPOOL_J: for (int j = 1; j < MAXPOOL_K; ++j)
                if (a1[o][t * MAXPOOL_STRIDE + j] > m) m = a1[o][t * MAXPOOL_STRIDE + j];
            p1[o][t] = m;
        }
    }

    // conv2 -> relu2. Same shape as conv1, over the pooled time axis.
    CONV2_O: for (int o = 0; o < CONV2_OUT; ++o) {
        CONV2_T: for (int t = 0; t < T2; ++t) {
            acc_t acc = conv2_b[o];
            CONV2_I: for (int i = 0; i < CONV2_IN; ++i)
                CONV2_TAP: for (int k = 0; k < CONV2_K; ++k) {
                    const int s = t + k - CONV2_PAD_L;
                    // Zero padding as a zero operand, not as a skipped add.
                    // Guarding the accumulate makes every product depend on
                    // the one before it, and HLS then schedules the chain at
                    // one add per cycle however wide CONV2_I is unrolled.
                    // Feeding a zero leaves the sum associative instead, so it
                    // can be balanced into a tree. Same arithmetic: w * 0 = 0.
                    // The index is clamped as well as the value, because the
                    // read is speculated in hardware and s reaches -1 and T2.
                    const bool pad = (s < 0 || s >= T2);
                    const int sc = pad ? 0 : s;
                    const relu1_t v = pad ? relu1_t(0) : p1[i][sc];
                    acc += conv2_w[(o * CONV2_IN + i) * CONV2_K + k] * v;
                }
            a2[o][t] = requantize(acc, CONV2_SHIFT, CONV2_LO, CONV2_HI);
        }
    }

    // The furthest element MAXPOOL_J reads is at
    // (MAXPOOL_OUT - 1) * MAXPOOL_STRIDE + MAXPOOL_K - 1, and a1 holds
    // NN_WINDOW per channel. This is the check the old one could not be: it
    // relates the pool's geometry to the buffer it reads, so it holds whatever
    // formula produced MAXPOOL_OUT. The old assertion recomputed the length
    // from the same two numbers the exporter used and agreed with itself.
    static_assert((MAXPOOL_OUT - 1) * MAXPOOL_STRIDE + MAXPOOL_K <= NN_WINDOW,
                  "the max pool reads past the end of a1.");

    // conv2 pads to keep its length, so the global pool collapses exactly what
    // the max pool left. Both come from one derivation in export_config.py, so
    // this catches the two #defines drifting apart, nothing deeper.
    static_assert(POOL_SIZE == MAXPOOL_OUT,
                  "POOL_SIZE disagrees with MAXPOOL_OUT.");

    // global pool: sum all POOL_SIZE first, then shift once. Dividing first
    // and requantizing after rounds twice and drifts an LSB — this is what
    // Brevitas does, and int_model.py checked it.
    POOL_O: for (int o = 0; o < CONV2_OUT; ++o) {
        acc_t s = 0;
        POOL_T: for (int t = 0; t < POOL_SIZE; ++t) {
            s += a2[o][t];
        }
        g[o] = requantize(s, POOL_SHIFT, POOL_LO, POOL_HI);
    }

    // fc1 -> relu3
    FC1_O: for (int o = 0; o < FC1_OUT; ++o) {
        acc_t acc = fc1_b[o];
        FC1_I: for (int i = 0; i < FC1_IN; ++i) {
            acc += fc1_w[o * FC1_IN + i] * g[i];
        }
        h[o] = requantize(acc, FC1_SHIFT, FC1_LO, FC1_HI);
    }

    // fc2 -> raw accumulators. No shift and no clamp: argmax is scale
    // invariant, so the PS takes it as it stands and the testbench can
    // compare bit exactly instead of by argmax.
    FC2_O: for (int o = 0; o < FC2_OUT; ++o) {
        acc_t acc = fc2_b[o];
        FC2_I: for (int i = 0; i < FC2_IN; ++i) {
            acc += fc2_w[o * FC2_IN + i] * h[i];
        }
        out[o] = ap_int<32>(acc);
    }
}
