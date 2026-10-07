"""Coloca o LibrAI no ar a partir deste computador, com um link público.

Use pelo ``publicar.cmd`` (raiz do projeto), que liga o modo produção com
o arquivo ``.env.publico``. O comando:

1. prepara os arquivos estáticos (``collectstatic``) e confere o banco;
2. sobe o servidor de produção (waitress) só em 127.0.0.1 — ninguém da
   rede acessa o computador diretamente;
3. abre um túnel da Cloudflare (``cloudflared``), que dá um link https
   público apontando para esse servidor, e mostra o link.

O link muda a cada vez que o túnel é ligado. Enquanto esta janela estiver
aberta (e o computador ligado, sem dormir), o site fica no ar; Ctrl+C
desliga tudo.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from .. import saida_segura

PADRAO_LINK = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
LOCAIS_CLOUDFLARED = (
    Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"),
    Path(r"C:\Program Files\cloudflared\cloudflared.exe"),
)
ARQUIVO_LINK = Path(settings.BASE_DIR) / "dados" / "link_publico.txt"


def achar_cloudflared():
    caminho = shutil.which("cloudflared")
    if caminho:
        return caminho
    for local in LOCAIS_CLOUDFLARED:
        if local.exists():
            return str(local)
    return None


def link_na_linha(linha):
    """Link público do túnel, se a linha do cloudflared o contiver."""
    achado = PADRAO_LINK.search(linha)
    return achado.group(0) if achado else None


class Command(BaseCommand):
    help = "Coloca o site no ar a partir deste computador (waitress + túnel da Cloudflare)."

    def add_arguments(self, parser):
        parser.add_argument("--porta", type=int, default=8080, help="Porta local do servidor (padrão 8080).")
        parser.add_argument("--sem-tunel", action="store_true", help="Só o servidor local, sem link público.")

    def handle(self, *args, **opcoes):
        saida_segura()
        if not settings.PRODUCAO:
            raise CommandError(
                "Rode pelo publicar.cmd (ele liga o modo produção com o .env.publico)."
            )
        self.preparar()
        porta = opcoes["porta"]
        self.subir_servidor(porta)
        if opcoes["sem_tunel"]:
            self.stdout.write(f"Servidor local em http://127.0.0.1:{porta}/ (Ctrl+C para sair).")
            self.esperar()
            return
        cloudflared = achar_cloudflared()
        if not cloudflared:
            raise CommandError(
                "cloudflared não encontrado. Instale com: "
                "winget install --id Cloudflare.cloudflared -e"
            )
        tunel = subprocess.Popen(
            [cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{porta}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace",
        )
        try:
            self.mostrar_link(tunel)
            self.esperar(tunel)
        finally:
            tunel.terminate()
            ARQUIVO_LINK.unlink(missing_ok=True)
            self.stdout.write("Site desligado.")

    def preparar(self):
        self.stdout.write("Preparando os arquivos do site…")
        call_command("collectstatic", interactive=False, verbosity=0)
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            self.stdout.write("Atualizando o banco de dados…")
            call_command("migrate", verbosity=0)

    def subir_servidor(self, porta):
        from waitress import serve

        from config.wsgi import application

        servidor = threading.Thread(
            target=serve,
            kwargs={
                "app": application, "host": "127.0.0.1", "port": porta, "threads": 8,
                "ident": "LibrAI",
                # O túnel (cloudflared, na mesma máquina) avisa que a conexão
                # original era https; sem isto o waitress descarta o aviso.
                "trusted_proxy": "127.0.0.1",
                "trusted_proxy_headers": "x-forwarded-proto",
            },
            daemon=True,
        )
        servidor.start()

    def mostrar_link(self, tunel):
        self.stdout.write("Abrindo o túnel da Cloudflare (leva alguns segundos)…")
        inicio = time.monotonic()
        for linha in tunel.stdout:
            link = link_na_linha(linha)
            if link:
                ARQUIVO_LINK.parent.mkdir(parents=True, exist_ok=True)
                ARQUIVO_LINK.write_text(link + "\n", encoding="utf-8")
                faixa = "=" * 64
                self.stdout.write(self.style.SUCCESS(
                    f"\n{faixa}\n  LibrAI NO AR:  {link}\n"
                    f"  Gravar/treinar (equipe):  {link}/entrar/\n{faixa}\n"
                ))
                self.stdout.write(
                    "Mande o link para a equipe. Ele muda a cada vez que você liga o site.\n"
                    "Deixe esta janela aberta e o computador sem dormir. Ctrl+C desliga.\n"
                )
                # O cloudflared continua escrevendo; descarta sem travar.
                threading.Thread(target=lambda: [None for _ in tunel.stdout], daemon=True).start()
                return
            if time.monotonic() - inicio > 60:
                break
        raise CommandError("O túnel não respondeu. Confira a internet e tente de novo.")

    def esperar(self, tunel=None):
        try:
            while tunel is None or tunel.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            return
        raise CommandError("O túnel caiu (internet instável?). Rode o publicar.cmd de novo.")
