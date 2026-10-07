"""Tira do ar o site ligado pelo publicar.cmd (servidor + túnel).

    desligar.cmd                 (na pasta do projeto)
    python manage.py desligar

Acha o processo que escuta na porta do publicar (8080), confere que é
mesmo o ``manage.py publicar`` (nunca derruba outro programa) e o encerra
junto com o túnel da Cloudflare. A janela do publicar mostra "Pressione
qualquer tecla" e pode ser fechada.
"""
from __future__ import annotations

import json
import subprocess

from django.core.management.base import BaseCommand, CommandError

from .. import saida_segura
from .publicar import ARQUIVO_LINK


def processos():
    """{pid: (nome, linha de comando)} dos processos do Windows."""
    resultado = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Select-Object ProcessId, Name, CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    dados = json.loads(resultado.stdout or "[]")
    if isinstance(dados, dict):
        dados = [dados]
    return {d["ProcessId"]: (d.get("Name") or "", d.get("CommandLine") or "") for d in dados}


def pid_na_porta(saida_netstat, porta):
    """PID que escuta em 127.0.0.1:<porta>, lido da saída do ``netstat -ano``."""
    for linha in saida_netstat.splitlines():
        partes = linha.split()
        if len(partes) >= 5 and partes[0] == "TCP" and partes[1] == f"127.0.0.1:{porta}" \
                and partes[3] in ("LISTENING", "ESCUTANDO"):
            return int(partes[4])
    return None


def tunel_da_porta(linha_de_comando, porta):
    return "cloudflared" in linha_de_comando and f"127.0.0.1:{porta}" in linha_de_comando


class Command(BaseCommand):
    help = "Tira do ar o site ligado pelo publicar.cmd."

    def add_arguments(self, parser):
        parser.add_argument("--porta", type=int, default=8080)

    def handle(self, *args, **opcoes):
        saida_segura()
        porta = opcoes["porta"]
        netstat = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        ).stdout
        pid = pid_na_porta(netstat, porta)
        todos = processos()
        encerrados = 0
        if pid is not None:
            nome, comando = todos.get(pid, ("", ""))
            if "publicar" not in comando:
                raise CommandError(
                    f"A porta {porta} está com outro programa ({nome or 'desconhecido'}, PID {pid}); "
                    "não foi mexido nele."
                )
            # /T: leva junto o túnel, que é filho do servidor.
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=60)
            encerrados += 1
        for outro, (nome, comando) in todos.items():
            if outro != pid and tunel_da_porta(comando, porta):
                subprocess.run(["taskkill", "/PID", str(outro), "/F"], capture_output=True, timeout=60)
                encerrados += 1
        if encerrados:
            ARQUIVO_LINK.unlink(missing_ok=True)
            self.stdout.write(self.style.SUCCESS("LibrAI desligado: o site e o link saíram do ar."))
        else:
            self.stdout.write("O site já estava desligado.")
