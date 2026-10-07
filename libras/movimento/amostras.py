"""Persistência das amostras temporais de sinais por movimento.

As amostras são gravadas pela câmera do OpenCV (``libras.movimento.gravacao``,
usado pela página do sinal e pelo comando gravar_movimento) e
persistidas como sequências de landmarks em arquivos JSON em
``dados/amostras_movimento/<id>-<sinal>/<amostra>.json`` (MEDIA_ROOT);
o banco guarda os metadados e o caminho de cada arquivo.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify

from ..models import AmostraMovimento, Sinal

# Versão 2: cada frame também registra a mão detectada ("mao").
FORMATO_VERSAO = 2
VERSOES_SUPORTADAS = (1, 2)
DURACAO_MAX_MS = 30_000
FRAMES_MIN_VALIDOS = 10
LANDMARKS_POR_MAO = 21
VALORES_POR_LANDMARK = 3


class AmostraInvalida(Exception):
    """Amostra temporal rejeitada pela validação."""


def pasta_do_sinal(sinal):
    """Pasta das amostras do sinal: id + título, ex.: ``2-j``.

    O id garante que a pasta seja única; o título deixa claro de qual
    sinal ela é. Se o título mudar, as amostras antigas continuam onde
    estão (o caminho de cada uma fica salvo no banco).
    """
    return f"{sinal.pk}-{slugify(sinal.titulo) or 'sinal'}"


def caminho_relativo(amostra):
    """Caminho do JSON da amostra relativo a MEDIA_ROOT."""
    return f"{pasta_do_sinal(amostra.sinal)}/{amostra.pk}.json"


def _caminho_absoluto(amostra):
    return Path(settings.MEDIA_ROOT) / caminho_relativo(amostra)


def salvar_amostra(sinal, sequencia, origem="opencv"):
    """Valida a sequência, grava o arquivo JSON e registra a amostra.

    O arquivo é nomeado com o id gerado pelo banco; em caso de falha de
    escrita o registro é revertido para não deixar metadados órfãos.
    ``origem`` registra o caminho da captura: "opencv" (câmera do
    reconhecimento) ou "navegador" (amostras antigas, da captura que
    passava pelo navegador e foi substituída).
    """
    validos = sum(1 for frame in sequencia if frame["landmarks"] is not None)
    if validos < FRAMES_MIN_VALIDOS:
        raise AmostraInvalida(
            f"São necessários pelo menos {FRAMES_MIN_VALIDOS} frames com a mão detectada."
        )
    duracao_ms = max(sequencia[-1]["timestamp_ms"] - sequencia[0]["timestamp_ms"], 0)
    fps = (
        round((len(sequencia) - 1) / (duracao_ms / 1000), 1)
        if duracao_ms > 0
        else 0.0
    )
    amostra = AmostraMovimento.objects.create(
        sinal=sinal,
        quantidade_frames=len(sequencia),
        duracao_ms=duracao_ms,
        fps=fps,
        quantidade_landmarks=LANDMARKS_POR_MAO,
        versao_features=FORMATO_VERSAO,
    )
    conteudo = {
        "version": FORMATO_VERSAO,
        "sinal_id": sinal.pk,
        "quantidade_frames": len(sequencia),
        "quantidade_frames_validos": validos,
        "duracao_ms": duracao_ms,
        "fps": fps,
        "quantidade_landmarks": LANDMARKS_POR_MAO,
        "origem": origem,
        "frames": sequencia,
    }
    try:
        caminho = _caminho_absoluto(amostra)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(conteudo), encoding="utf-8")
        amostra.arquivo_dados = caminho_relativo(amostra)
        amostra.save(update_fields=["arquivo_dados", "atualizado_em"])
    except OSError:
        amostra.delete()
        raise AmostraInvalida("Não foi possível salvar o arquivo da amostra.")
    return amostra


def ler_sequencia(amostra):
    """Lê o JSON da amostra com verificação de caminho seguro.

    O caminho registrado nunca pode apontar para fora de MEDIA_ROOT,
    impedindo acesso arbitrário ao sistema de arquivos.
    """
    raiz = Path(settings.MEDIA_ROOT).resolve()
    caminho = (Path(settings.MEDIA_ROOT) / amostra.arquivo_dados).resolve()
    if not caminho.is_relative_to(raiz):
        raise AmostraInvalida("Caminho de arquivo inválido.")
    if not caminho.is_file():
        raise AmostraInvalida("Arquivo da amostra não encontrado.")
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AmostraInvalida("Arquivo da amostra corrompido.")


def apagar_amostra(amostra):
    """Apaga a amostra: o registro no banco e o arquivo JSON correspondente.

    A remoção do arquivo é melhor esforço (com checagem de caminho seguro);
    se falhar, o registro ainda é apagado — o arquivo órfão fica em
    ``dados/amostras_movimento/``, que é ignorada pelo Git.
    """
    if amostra.arquivo_dados:
        try:
            raiz = Path(settings.MEDIA_ROOT).resolve()
            caminho = (Path(settings.MEDIA_ROOT) / amostra.arquivo_dados).resolve()
            if caminho.is_relative_to(raiz):
                caminho.unlink(missing_ok=True)
        except OSError:
            pass
    amostra.delete()


def sinal_de_movimento(sinal):
    """Confere se o sinal aceita gravação de amostras temporais."""
    return sinal.tipo == Sinal.Tipo.MOVIMENTO
