"""Modo teste: placar de acerto e de tempo do reconhecimento ao vivo.

Cada teste (uma letra, N tentativas feitas na câmera) vira uma linha em
``dados/testes_ao_vivo.jsonl``, com quem testou, quando, por onde (link
público ou no próprio PC — o tempo muda muito) e a versão dos modelos.
Serve para medir antes e depois de cada mudança e não piorar uma letra sem
perceber.
"""
from __future__ import annotations

import json
import math
import threading
from collections import defaultdict
from datetime import datetime

from . import caminhos

TENTATIVAS_MAX = 50
TEMPO_MAX_MS = 10_000
_lock = threading.Lock()


class ResultadoInvalido(Exception):
    """Resultado de teste com dados fora do esperado."""


def _arquivo():
    # Lido na hora da chamada: os testes redirecionam o arquivo.
    return caminhos.TESTES_AO_VIVO


def _inteiro(valor, minimo, maximo, nome):
    if isinstance(valor, bool) or not isinstance(valor, int) or not minimo <= valor <= maximo:
        raise ResultadoInvalido(f"Valor inválido em {nome}.")
    return valor


def validar(dados, letras_validas):
    """Confere o resultado enviado pela página; devolve só os campos aceitos."""
    if not isinstance(dados, dict):
        raise ResultadoInvalido("Dados inválidos.")
    letra = dados.get("letra")
    if letra not in letras_validas:
        raise ResultadoInvalido("Letra inválida para o teste.")
    tentativas = _inteiro(dados.get("tentativas"), 1, TENTATIVAS_MAX, "tentativas")
    acertos = _inteiro(dados.get("acertos"), 0, tentativas, "acertos")
    tempos = dados.get("tempos_ms", [])
    if (
        not isinstance(tempos, list)
        or len(tempos) != acertos
        or not all(
            not isinstance(t, bool) and isinstance(t, (int, float)) and math.isfinite(t)
            and 0 <= t <= TEMPO_MAX_MS
            for t in tempos
        )
    ):
        raise ResultadoInvalido("Tempos inválidos.")
    vistos = dados.get("erros", {})
    if (
        not isinstance(vistos, dict)
        or len(vistos) > 30
        or not all(isinstance(k, str) and 0 < len(k) <= 40 for k in vistos)
    ):
        raise ResultadoInvalido("Erros inválidos.")
    erros = {k: _inteiro(v, 1, tentativas, "erros") for k, v in vistos.items()}
    if sum(erros.values()) > tentativas - acertos:
        raise ResultadoInvalido("Erros não batem com as tentativas.")
    return {
        "letra": letra,
        "tentativas": tentativas,
        "acertos": acertos,
        "tempos_ms": [round(float(t)) for t in tempos],
        "erros": erros,
    }


def registrar(resultado):
    """Acrescenta uma linha ao histórico."""
    arquivo = _arquivo()
    linha = json.dumps(resultado, ensure_ascii=False) + "\n"
    with _lock:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        with arquivo.open("a", encoding="utf-8") as saida:
            saida.write(linha)


def historico(limite=40):
    """Testes mais recentes primeiro, cada um com ``percentual``,
    ``tempo_medio_ms`` e a ``variacao`` em relação ao teste anterior da
    mesma letra (feito pelo mesmo caminho: link ou PC)."""
    try:
        linhas = _arquivo().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    registros = []
    for linha in linhas:
        try:
            registro = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if isinstance(registro, dict) and registro.get("tentativas"):
            registros.append(registro)
    anteriores = defaultdict(lambda: None)
    for registro in registros:  # do mais antigo para o mais novo
        registro["percentual"] = round(100 * registro["acertos"] / registro["tentativas"])
        try:
            registro["quando_texto"] = datetime.fromisoformat(registro["quando"]).strftime("%d/%m/%Y %H:%M")
        except (KeyError, TypeError, ValueError):
            registro["quando_texto"] = "—"
        tempos = registro.get("tempos_ms") or []
        registro["tempo_medio_ms"] = round(sum(tempos) / len(tempos)) if tempos else None
        chave = (registro.get("letra"), registro.get("por_onde"))
        anterior = anteriores[chave]
        registro["variacao"] = (
            registro["percentual"] - anterior["percentual"] if anterior is not None else None
        )
        anteriores[chave] = registro
    return list(reversed(registros))[:limite]
