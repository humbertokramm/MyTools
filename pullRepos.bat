@echo off

set startLocal=C:%HOMEPATH%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
set startFile=UpdateRepo.lnk
copy "%PYTHONPATH%\%startFile%" "%startLocal%"

::pip install -r %PYTHONPATH%\requirements.txt
cls

python updateLibScript.py -f



