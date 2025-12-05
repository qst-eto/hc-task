conda activate rpi-arduino
cd homecage-task
ARGS=$(./code/cat pre_arg.txt)
python ./code/main.py $ARGS

