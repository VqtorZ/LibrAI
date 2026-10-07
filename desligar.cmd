@echo off
rem Tira do ar o site ligado pelo publicar.cmd (servidor + link publico).
cd /d "%~dp0"
.venv\Scripts\python.exe manage.py desligar %*
