#!/bin/bash

echo "start"
cd /home/user

#step1
sudo apt update && sudo apt full-upgrade -y
#sudo apt install -y git curl wget build-essential unzip
sudo usermod -aG dialout,tty user

#step2 Miniconda
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
bash miniconda.sh -b -p $HOME/miniconda3
echo 'export PATH="$HOME/miniconda3/bin:PATH"' >> ~/.bashrc
source ~/.bashrc
conda init bash
source ~/.bashrc

#step3 VScode
#sudo apt install code

#step4 conda設定
# 環境名: rpi-arduino
#source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda create -y -n rpi-arduino python=3.11
conda activate rpi-arduino

# 最低限：pyserial は必須
conda install -y pyserial
conda install -y pygame