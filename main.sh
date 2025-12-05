conda activate rpi-arduino
cd homecage-task
ARGS=$(cat pre_arg.txt)
python ./code/main.py $ARGS
