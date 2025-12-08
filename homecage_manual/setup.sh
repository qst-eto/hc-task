#!/bin/bash

echo "start"
cd /home/user

#step1
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git curl wget build-essential unzip
sudo usermod -aG dialout,tty user

#step2 Miniforge
cd ~
curl -LO https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh
bash Miniforge3-Linux-aarch64.sh -b -p $HOME/miniforge3

echo 'export PATH="$HOME/miniforge3/bin:\\$PATH\\"' >> ~/.bashrc
source ~/.bashrc
source "$HOME/miniforge3/etc/profile.d/conda.sh"
#step3 conda設定
# 環境名: rpi-arduino
conda create -y -n rpi-arduino python=3.11
conda activate rpi-arduino

# 最低限：pyserial は必須
conda install -y pyserial
conda install -y pygame
codna install -y ipykernel

conda init
source ~/.bashrc

#step4 VScode
sudo apt install code
code --install-extension ms-python.python
code --install-extension ms-toolsai.jupyter