@echo off
rem O DMWLua faz chdir para %LUA_DEV% ao iniciar, então o script precisa ir com caminho absoluto.
lua "%~dp0jtag.lua" %*
