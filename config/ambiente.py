"""Configuração por ambiente (computador local × servidor no ar).

No servidor, as configurações sensíveis ficam num arquivo ``.env`` na raiz
do projeto (fora do Git, ver ``.gitignore``), uma por linha::

    LIBRAI_PRODUCAO=1
    LIBRAI_SECRET_KEY=<chave longa e aleatória>
    LIBRAI_HOSTS=seuusuario.pythonanywhere.com

Variáveis já definidas no sistema têm prioridade sobre o arquivo. Sem
``.env`` (o computador local), tudo continua como sempre: modo de
desenvolvimento, só em 127.0.0.1/localhost.
"""
from __future__ import annotations

import os
from pathlib import Path


def carregar_env(caminho: Path) -> None:
    """Lê ``CHAVE=valor`` do arquivo para ``os.environ`` (sem sobrescrever)."""
    try:
        linhas = caminho.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return
    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        os.environ.setdefault(chave, valor)


def ligado(nome: str, padrao: bool = False) -> bool:
    valor = os.environ.get(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes", "on")


def lista(nome: str) -> list[str]:
    return [item.strip() for item in os.environ.get(nome, "").split(",") if item.strip()]
