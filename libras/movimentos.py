"""Coleta temporal de sinais por movimento.

Pipeline separada do reconhecimento estático: recebe frames capturados
pelo navegador, extrai os landmarks de cada frame com o MediaPipe e
persiste a sequência temporal em arquivos JSON dentro de MEDIA_ROOT.
"""
from __future__ import annotations

import base64
import binascii
import json
import threading
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from django.conf import settings

from .models import AmostraMovimento, Sinal

# Versão 2: cada frame também registra a mão detectada ("mao").
FORMATO_VERSAO = 2
VERSOES_SUPORTADAS = (1, 2)
MAOS_VALIDAS = ("Right", "Left")
DURACAO_MAX_MS = 30_000
FRAMES_MAX = 500
FRAMES_MIN_VALIDOS = 10
LANDMARKS_POR_MAO = 21
VALORES_POR_LANDMARK = 3


class AmostraInvalida(Exception):
    """Amostra temporal rejeitada pela validação."""


def validar_payload(dados):
    """Confere o JSON enviado pela gravação e devolve [(timestamp, bytes)].

    Os timestamps são milissegundos desde o início da gravação e a imagem
    é um JPEG codificado em base64. Nada vindo do cliente é confiado sem
    checagem: estrutura, tipos, limites e duração.
    """
    if not isinstance(dados, dict):
        raise AmostraInvalida("Formato de dados inválido.")
    frames = dados.get("frames")
    if not isinstance(frames, list) or not frames:
        raise AmostraInvalida("Nenhum frame recebido.")
    if len(frames) > FRAMES_MAX:
        raise AmostraInvalida(f"Máximo de {FRAMES_MAX} frames por amostra.")
    saida = []
    for frame in frames:
        if not isinstance(frame, dict):
            raise AmostraInvalida("Frame inválido.")
        timestamp_ms = frame.get("timestamp_ms")
        imagem = frame.get("imagem")
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
            raise AmostraInvalida("timestamp_ms inválido.")
        if not isinstance(imagem, str) or not imagem:
            raise AmostraInvalida("Imagem ausente no frame.")
        try:
            dados_imagem = base64.b64decode(imagem, validate=True)
        except (binascii.Error, ValueError):
            raise AmostraInvalida("Imagem corrompida no frame.")
        saida.append((timestamp_ms, dados_imagem))
    duracao = saida[-1][0] - saida[0][0]
    if duracao < 0:
        raise AmostraInvalida("Timestamps fora de ordem.")
    if duracao > DURACAO_MAX_MS:
        raise AmostraInvalida("A gravação excede 30 segundos.")
    return saida


_lock = threading.Lock()
_hands = None


def _detectar():
    """Detector compartilhado; chamar somente com ``_lock`` adquirido."""
    global _hands
    if _hands is None:
        _hands = mp.solutions.hands.Hands(
            static_image_mode=True,
            max_num_hands=1,
            model_complexity=0,
            min_detection_confidence=0.6,
        )
    return _hands


def extrair_landmarks(frames):
    """Extrai os landmarks de cada frame e devolve a sequência temporal.

    Frames sem mão detectada (ou ilegíveis) permanecem na sequência com
    ``landmarks: null`` — nada é descartado silenciosamente. Os valores
    são os 21 marcos crus do MediaPipe (x, y, z normalizados na imagem).
    ``mao`` guarda a lateralidade informada pelo MediaPipe ("Right" ou
    "Left"), usada pelo pipeline temporal para espelhar sinais feitos
    com a mão esquerda.
    """
    sequencia = []
    with _lock:
        hands = _detectar()
        for timestamp_ms, dados_imagem in frames:
            landmarks = None
            mao = None
            imagem = cv2.imdecode(
                np.frombuffer(dados_imagem, np.uint8), cv2.IMREAD_COLOR
            )
            if imagem is not None:
                resultado = hands.process(cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB))
                if resultado.multi_hand_landmarks:
                    pontos = resultado.multi_hand_landmarks[0].landmark
                    valores = []
                    for ponto in pontos:
                        valores.extend((float(ponto.x), float(ponto.y), float(ponto.z)))
                    if len(valores) == LANDMARKS_POR_MAO * VALORES_POR_LANDMARK:
                        landmarks = valores
                        mao = _lateralidade(resultado)
            sequencia.append(
                {"timestamp_ms": timestamp_ms, "landmarks": landmarks, "mao": mao}
            )
    return sequencia


def _lateralidade(resultado):
    """"Right"/"Left" da primeira mão detectada, ou None se indisponível."""
    try:
        rotulo = resultado.multi_handedness[0].classification[0].label
    except (AttributeError, IndexError, TypeError):
        return None
    return rotulo if rotulo in MAOS_VALIDAS else None


def caminho_relativo(amostra):
    """Caminho do JSON da amostra relativo a MEDIA_ROOT."""
    return f"movimentos/{amostra.sinal_id}/{amostra.pk}.json"


def _caminho_absoluto(amostra):
    return Path(settings.MEDIA_ROOT) / caminho_relativo(amostra)


def salvar_amostra(sinal, sequencia):
    """Valida a sequência, grava o arquivo JSON e registra a amostra.

    O arquivo é nomeado com o id gerado pelo banco; em caso de falha de
    escrita o registro é revertido para não deixar metadados órfãos.
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
    ``media/``, que é ignorada pelo Git.
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
