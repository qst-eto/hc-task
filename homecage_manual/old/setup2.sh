#step3 conda設定
# 環境名: rpi-arduino
conda create -n rpi-arduino python=3.11 -y
conda activate rpi-arduino

# 最低限：pyserial は必須
conda install -y pyserial
conda install pygame

#step4 VScode
sudo apt install code