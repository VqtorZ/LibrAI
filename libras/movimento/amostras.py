"""Amostras temporais de sinais por movimento: validação e persistência.

As amostras são gravadas no navegador (a câmera de quem está usando o
site, com o MediaPipe rodando ali) e chegam como quadros com os 21
pontos da mão. Cada amostra vira um JSON em
``dados/amostras_movimento/<id>-<sinal>/<amostra>.json`` (MEDIA_ROOT);
o banco guarda os metadados e o caminho do arquivo.

Formato dos pontos (versão 3): x e z multiplicados pela proporção da
imagem (largura / altura) e já espelhados como numa selfie — o mesmo
gesto dá os mesmos números em qualquer webcam.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify

from ..models import AmostraMovimento, Sinal

# Versão 3: pontos do navegador (MediaPipe Tasks) corrigidos pela proporção.
# As versões 1 e 2 (câmera do servidor) continuam legíveis, mas ficam fora
# dos treinos: os pontos daquela época foram medidos de outro jeito.
FORMATO_VERSAO = 3
VERSOES_SUPORTADAS = (1, 2, 3)
DURACAO_MAX_MS = 30_000
FRAMES_MAX = 1200
FRAMES_MIN_VALIDOS = 10
LANDMARKS_POR_MAO = 21
VALORES_POR_LANDMARK = 3
VALORES_POR_FRAME = LANDMARKS_POR_MAO * VALORES_POR_LANDMARK
MAOS_VALIDAS = ("Right", "Left")
# Coordenadas normalizadas ficam perto de 0..2; muito além disso é lixo.
LIMITE_COORDENADA = 10.0


class AmostraInvalida(Exception):
    """Amostra temporal rejeitada pela validação."""


def _numero(valor):
    return (
        not isinstance(valor, bool)
        and isinstance(valor, (int, float))
        and math.isfinite(valor)
    )


def validar_marcos(marcos):
    """63 valores numéricos da mão (ou None); levanta AmostraInvalida."""
    if marcos is None:
        return None
    if (
        not isinstance(marcos, list)
        or len(marcos) != VALORES_POR_FRAME
        or not all(_numero(v) and abs(v) <= LIMITE_COORDENADA for v in marcos)
    ):
        raise AmostraInvalida("Pontos da mão inválidos.")
    return [float(v) for v in marcos]


def validar_quadros(dados, maximo=FRAMES_MAX):
    """Quadros enviados pelo navegador → lista no formato das amostras.

    Cada quadro: ``{"t": ms, "marcos": [63] ou null, "mao": ...}``. Nada
    vindo do navegador é confiado sem checagem: tipos, limites e ordem.
    """
    if not isinstance(dados, list) or not dados:
        raise AmostraInvalida("Nenhum quadro recebido.")
    if len(dados) > maximo:
        raise AmostraInvalida(f"Máximo de {maximo} quadros por envio.")
    quadros = []
    anterior = None
    for quadro in dados:
        if not isinstance(quadro, dict) or not _numero(quadro.get("t")) or quadro["t"] < 0:
            raise AmostraInvalida("Quadro inválido.")
        t = int(quadro["t"])
        if anterior is not None and t < anterior:
            raise AmostraInvalida("Quadros fora de ordem.")
        anterior = t
        mao = quadro.get("mao")
        if mao is not None and mao not in MAOS_VALIDAS:
            raise AmostraInvalida("Mão inválida.")
        marcos = validar_marcos(quadro.get("marcos"))
        quadros.append({"timestamp_ms": t, "landmarks": marcos, "mao": mao if marcos else None})
    return quadros


def sequencia_de_gravacao(dados):
    """Quadros de uma gravação → sequência com tempo a partir de zero."""
    quadros = validar_quadros(dados)
    inicio = quadros[0]["timestamp_ms"]
    if quadros[-1]["timestamp_ms"] - inicio > DURACAO_MAX_MS:
        raise AmostraInvalida("A gravação passou de 30 segundos.")
    for quadro in quadros:
        quadro["timestamp_ms"] -= inicio
    return quadros


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


def salvar_amostra(sinal, sequencia, origem="navegador"):
    """Valida a sequência, grava o arquivo JSON e registra a amostra.

    O arquivo é nomeado com o id gerado pelo banco; em caso de falha de
    escrita o registro é revertido para não deixar metadados órfãos.
    ``origem`` registra o caminho da captura ("navegador" nas amostras
    atuais; "opencv" nas antigas, da câmera do servidor).
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


def apagar_sinal(sinal):
    """Apaga o sinal inteiro: o cadastro, as amostras e os arquivos delas.

    Devolve quantas amostras foram apagadas. A pasta do sinal em
    ``dados/amostras_movimento/`` é removida se ficar vazia. (Tirar o
    sinal do modelo treinado é com ``classificador.remover_do_modelo``.)
    """
    amostras = list(sinal.amostras.all())
    pastas = set()
    for amostra in amostras:
        if amostra.arquivo_dados:
            pastas.add((Path(settings.MEDIA_ROOT) / amostra.arquivo_dados).parent)
        apagar_amostra(amostra)
    sinal.delete()
    raiz = Path(settings.MEDIA_ROOT).resolve()
    for pasta in pastas:
        try:
            pasta = pasta.resolve()
            if pasta != raiz and pasta.is_relative_to(raiz) and not any(pasta.iterdir()):
                pasta.rmdir()
        except OSError:
            pass
    return len(amostras)


def sinal_de_movimento(sinal):
    """Confere se o sinal aceita gravação de amostras temporais."""
    return sinal.tipo == Sinal.Tipo.MOVIMENTO
