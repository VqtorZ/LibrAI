"""Onde um movimento começa e termina (segmentação por velocidade).

Usada ao vivo (``ao_vivo``) e no treino, para recortar as gravações:
os dois lados comparam trechos equivalentes.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from .amostras import LANDMARKS_POR_MAO
from .trajetoria import normalizar_frame

# Segmentação de movimentos (``Segmentador``), calibrada com as
# gravações reais de J: mão em repouso fica em ~1–3,5 unidades/s
# (tremor natural) e o movimento do sinal em ~8–25 (unidades = forma
# normalizada + pulso em tamanhos de mão, por segundo).
VELOCIDADE_INICIO = 6.0      # média de 3 frames que inicia um movimento
VELOCIDADE_REPOUSO = 4.0     # abaixo disto a mão está parada
PAUSA_MS = 350               # tempo parado (ou sem mão) que encerra
PRE_MOVIMENTO_MS = 300       # contexto anterior incluído no trecho
DURACAO_MIN_MOVIMENTO_MS = 400
DURACAO_MAX_MOVIMENTO_MS = 4000


def _vetor_de_movimento(landmarks):
    """Forma normalizada + pulso em tamanhos de mão de um único frame."""
    pontos = np.asarray(landmarks, dtype=float).reshape(LANDMARKS_POR_MAO, 3)
    tamanho = float(np.linalg.norm(pontos[9, :2] - pontos[0, :2])) or 1.0
    return np.concatenate([normalizar_frame(landmarks), pontos[0, :2] / tamanho])


class Segmentador:
    """Detecta, frame a frame, onde um movimento começa e termina.

    O movimento começa quando a velocidade média (3 frames) passa de
    ``VELOCIDADE_INICIO`` e termina após ``PAUSA_MS`` com a mão parada
    ou fora do quadro (ou ao atingir ``DURACAO_MAX_MOVIMENTO_MS``).
    É usado ao vivo (``libras.ao_vivo``) e, no treino, para recortar
    as gravações — os dois lados comparam trechos equivalentes.
    """

    def __init__(self):
        self._anterior = None  # (timestamp_ms, vetor) do último frame com mão
        self._velocidades = deque(maxlen=3)
        self._inicio = None
        self._ultimo_movimento = None
        # Duração do último movimento descartado por ser curto (diagnóstico).
        self.descartado_ms = None

    @property
    def em_movimento(self):
        return self._inicio is not None

    def observar(self, timestamp_ms, landmarks):
        """Devolve ``(inicio_ms, fim_ms)`` quando um movimento termina."""
        self.descartado_ms = None
        if landmarks is None:
            self._anterior = None
            self._velocidades.clear()
        else:
            vetor = _vetor_de_movimento(landmarks)
            if self._anterior is not None:
                t_anterior, v_anterior = self._anterior
                dt = (timestamp_ms - t_anterior) / 1000
                if dt > 0:
                    self._velocidades.append(
                        float(np.linalg.norm(vetor - v_anterior)) / dt
                    )
            self._anterior = (timestamp_ms, vetor)
        velocidade = (
            sum(self._velocidades) / len(self._velocidades)
            if self._velocidades else 0.0
        )
        if self._inicio is None:
            if velocidade >= VELOCIDADE_INICIO:
                self._inicio = self._ultimo_movimento = timestamp_ms
            return None
        if landmarks is not None and velocidade >= VELOCIDADE_REPOUSO:
            self._ultimo_movimento = timestamp_ms
        parado = timestamp_ms - self._ultimo_movimento >= PAUSA_MS
        longo = timestamp_ms - self._inicio >= DURACAO_MAX_MOVIMENTO_MS
        if parado or longo:
            return self._fechar()
        return None

    def encerrar(self):
        """Fecha o movimento em aberto (fim de uma gravação)."""
        return self._fechar() if self._inicio is not None else None

    def _fechar(self):
        inicio, fim = self._inicio, self._ultimo_movimento
        self._inicio = self._ultimo_movimento = None
        # A duração mínima vale para o movimento em si, sem o contexto.
        if fim - inicio < DURACAO_MIN_MOVIMENTO_MS:
            self.descartado_ms = fim - inicio
            return None
        return inicio, fim


def recortar(frames, inicio, fim):
    """Frames do movimento ``(inicio, fim)`` mais o contexto anterior."""
    return [
        f for f in frames
        if inicio - PRE_MOVIMENTO_MS <= f["timestamp_ms"] <= fim
    ]


def segmentos(frames):
    """Todos os movimentos ``(inicio_ms, fim_ms)`` de uma gravação."""
    segmentador = Segmentador()
    encontrados = []
    for frame in frames:
        segmento = segmentador.observar(frame["timestamp_ms"], frame["landmarks"])
        if segmento:
            encontrados.append(segmento)
    final = segmentador.encerrar()
    if final:
        encontrados.append(final)
    return encontrados


def trecho_principal(frames):
    """Recorta o movimento mais longo da gravação.

    Descarta o que não é o sinal: a mão entrando no quadro logo após
    "Iniciar gravação" e saindo para clicar em "Parar" — movimentos
    curtos que, ao vivo, o reconhecedor nunca veria junto do sinal.
    Sem nenhum movimento detectado, a gravação inteira é usada.
    """
    encontrados = segmentos(frames)
    if not encontrados:
        return frames
    inicio, fim = max(encontrados, key=lambda s: s[1] - s[0])
    return recortar(frames, inicio, fim)
