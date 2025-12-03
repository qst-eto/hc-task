import os
import shutil
file_ori_dir='../test/'
file_new_dir='../moved_test/'
file_name=os.listdir(file_ori_dir)

for i in range (len(file_name)):
    shutil.move(file_ori_dir+file_name[i],file_new_dir)