// Hand-written. The testbench's view of the generated headers.
//
// Separate from weights.hpp so that nn_infer.cpp never pulls in 660 KB of
// test vectors it has no use for. Only nn_tb.cpp includes this.
//
// The width comes from weights.hpp rather than being named again here, so
// the vectors and the weights cannot be drawn from different widths. That
// was a real hazard while both shims spelled the width out: golden_w<N>.h
// holds the logits Brevitas produced for weights_w<N>.hpp, so a mismatched
// pair is one network being checked against another network's answers.

#ifndef CG4002_NN_GOLDEN_H
#define CG4002_NN_GOLDEN_H

#include "params.hpp"

#include NN_STR(NN_CAT(golden_w, NN_WIDTH).h)

#endif  // CG4002_NN_GOLDEN_H
