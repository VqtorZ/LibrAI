@echo off
rem Coloca o LibrAI no ar a partir deste computador, com um link publico.
rem Deixe esta janela aberta enquanto a equipe usa o site. Ctrl+C desliga.
cd /d "%~dp0"
set LIBRAI_ENV=.env.publico
.venv\Scripts\python.exe manage.py publicar %*
pause
