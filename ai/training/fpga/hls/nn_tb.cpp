#include "golden.h"
#include "nn_infer.hpp"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cerrno>

/**
 * This file serves as the testbench.
 */
int main(int argc, char **argv) {
    const bool cosim = (argc > 1 && strcmp(argv[1], "cosim") == 0);
    int n = cosim ? GOLDEN_COSIM_N : GOLDEN_N;
    if (cosim && argc > 2) {
        char *end = nullptr;
        errno = 0;
        const long count = std::strtol(argv[2], &end, 10);
        if (errno != 0 || end == argv[2] || *end != '\0' ||
            count < 1 || count > GOLDEN_N) {
            std::fprintf(stderr, "cosim vector count must be between 1 and %d\n", GOLDEN_N);
            return 1;
        }
        n = static_cast<int>(count);
    }

    if (cosim) {
        std::printf("Co-simulation C testbench: %d vectors. HLS also runs this before RTL simulation.\n", n);
        std::fflush(stdout);
    }

    int failures = 0;

    for (int v = 0; v < n; v++) {
        ap_int<8> in[NN_CH * NN_WINDOW];
        ap_int<32> out[NN_CLASSES];

        for (int i = 0; i < NN_CH * NN_WINDOW; ++i) {
            in[i] = golden_in[v * NN_CH * NN_WINDOW + i];
        }

        nn_infer(in, out);

        for (int k = 0; k < NN_CLASSES; ++k) {
            long long want = golden_out[v * NN_CLASSES + k];
            long long got = out[k];

            if (got != want) {
                printf("vector %d (label %d) class %d: want %lld, got %lld\n", 
                v, golden_label[v], k, want, got);

                ++failures;
                break;
            }
        }
    }

    printf("%d of %d vectors mismatched\n", failures, n);
    if (cosim) {
        std::printf("C testbench finished; wait for HLS 'C/RTL co-simulation finished: PASS' to confirm RTL verification.\n");
        std::fflush(stdout);
    }
    return failures != 0;
}
