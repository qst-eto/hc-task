conda activate rpi-arduino
cd ~/Desktop/homecage-task
ARGS=$(cat ./pre_arg.txt)
python ./code/main.py $ARGS