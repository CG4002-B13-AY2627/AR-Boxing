#ifndef CG4002_NN_INFER_HPP
#define CG4002_NN_INFER_HPP

#include "params.hpp"

void nn_infer(const ap_int<8> in[NN_CH * NN_WINDOW], ap_int<32> out[NN_CLASSES]);

#endif