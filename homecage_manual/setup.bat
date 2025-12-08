@echo off

echo hostname:
SET /P arg1=

echo username:
SET /P arg2=

echo password
set /p arg3=

python setup.py %arg1% %arg2% %arg3%
PAUSE