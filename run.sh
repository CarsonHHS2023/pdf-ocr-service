#!/bin/bash
export PADDLE_ENABLE_PIR=0
export FLAGS_use_mkldnn=0
export PADDLE_MKL_DNN_ENABLED=0
export MKLDNN_VERBOSE=0
exec python app.py
