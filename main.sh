#!/bin/bash -l
source ~/miniforge3/etc/profile.d/conda.sh
conda activate rpi-arduino
cd ./homecage-task
ARGS=$(cat ./pre_arg.txt)
python ./code/main.py $ARGS
