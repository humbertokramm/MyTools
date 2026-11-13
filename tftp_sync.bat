@echo off
rem Abre o sincronismo da pasta TFTP com o pc da camara, na bandeja e sem janela
start "" "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" "%~dp0tftp_sync.py"
