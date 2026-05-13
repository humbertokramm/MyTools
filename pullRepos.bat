@echo off

set localsouce=C:\Projetos\
set startLocal=C:%HOMEPATH%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
set startFile=UpdateRepo.lnk
copy "%localsouce%scripts\%startFile%" "%startLocal%"

::pip install -r C:\Altium\scripts\requirements.txt
cls

python updateLibScript.py -f



