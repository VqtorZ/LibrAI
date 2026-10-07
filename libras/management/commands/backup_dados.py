"""Cópia de segurança de todos os dados num único .zip.

    python manage.py backup_dados

Gera ``backups/librai-AAAA-MM-DD-HHMM.zip`` com o banco (copiado de forma
consistente, mesmo com o site no ar), as amostras do alfabeto, as
amostras de movimento e os modelos treinados. No servidor, baixe o .zip
pela aba Files do PythonAnywhere. Para restaurar, descompacte na raiz do
projeto (com o site parado).
"""
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand

from ... import caminhos
from .. import saida_segura

PASTAS = (
    caminhos.AMOSTRAS_ESTATICAS.parent,
    caminhos.AMOSTRAS_MOVIMENTO,
    caminhos.MODELOS_TREINADOS,
)


class Command(BaseCommand):
    help = "Gera um .zip com o banco, as amostras e os modelos (em backups/)."

    def add_arguments(self, parser):
        parser.add_argument("--destino", help="Pasta do .zip (padrão: backups/ na raiz do projeto).")

    def handle(self, *args, **options):
        saida_segura()
        pasta = Path(options["destino"]) if options["destino"] else caminhos.RAIZ / "backups"
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"librai-{datetime.now():%Y-%m-%d-%H%M}.zip"
        total = 0
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as arquivo_zip:
            if caminhos.BANCO.exists():
                with tempfile.TemporaryDirectory() as temporaria:
                    copia = Path(temporaria) / "banco.sqlite3"
                    origem = sqlite3.connect(caminhos.BANCO)
                    alvo = sqlite3.connect(copia)
                    try:
                        origem.backup(alvo)  # cópia consistente, mesmo em uso
                    finally:
                        alvo.close()
                        origem.close()
                    arquivo_zip.write(copia, caminhos.BANCO.relative_to(caminhos.RAIZ).as_posix())
                    total += 1
            for raiz in PASTAS:
                if not raiz.exists():
                    continue
                for arquivo in sorted(raiz.rglob("*")):
                    if arquivo.is_file() and not arquivo.name.endswith(".tmp"):
                        arquivo_zip.write(arquivo, arquivo.relative_to(caminhos.RAIZ).as_posix())
                        total += 1
        tamanho_mb = destino.stat().st_size / 1_000_000
        self.stdout.write(self.style.SUCCESS(
            f"Backup criado: {destino} ({total} arquivos, {tamanho_mb:.1f} MB)"
        ))
