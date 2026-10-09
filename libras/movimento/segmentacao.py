"""Onde um movimento começa e termina (segmentação por velocidade).

Usada ao vivo (``ao_vivo``) e no treino, para recortar as gravações:
os dois lados comparam trechos equivalentes.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from .amostras import LANDMARKS_POR_MAO
from .trajetoria import normalizar_frame

# Segmentação de movimentos (``Segmentador``). Unidades = forma
# normalizada + pulso em tamanhos de mão, por segundo.
#
# A velocidade compara a MÉDIA das últimas posições com a média de ~150 ms
# antes (não quadro a quadro). Dedos escondidos (M, N, Q com a mão virada
# para baixo) fazem o detector "chutar" a posição deles a cada quadro: um
# tremor que, quadro a quadro, parecia movimento rápido. Na média e numa
# janela maior o tremor se cancela, e o movimento de verdade (que anda
# sempre para o mesmo lado) não. Medido em 49 gravações de J do navegador:
# mão parada caiu de até 4,6 para até 0,5; movimento continua 100% acima
# do limite (5% mais lentos ~10,5). Com tremor simulado de ~6 px nos dedos,
# o "Analisando" falso caiu de 49/49 para 1/49.
VELOCIDADE_INICIO = 6.0      # velocidade que inicia um movimento
VELOCIDADE_REPOUSO = 4.0     # abaixo disto a mão está parada
JANELA_VELOCIDADE_MS = 150   # distância no tempo entre as duas médias
QUADROS_NA_MEDIA = 4         # posições em cada média
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
        # (timestamp_ms, vetor) dos quadros recentes com mão, em ordem.
        self._recentes = deque()
        # Última velocidade medida (aparece no modo diagnóstico do site).
        self.velocidade = 0.0
        self._inicio = None
        self._ultimo_movimento = None
        # Duração do último movimento descartado por ser curto (diagnóstico).
        self.descartado_ms = None

    @property
    def em_movimento(self):
        return self._inicio is not None

    @property
    def inicio_ms(self):
        """Quando o movimento em andamento começou (None se parado)."""
        return self._inicio

    def _medir(self, timestamp_ms, landmarks):
        """Velocidade: média das últimas posições × média de ~150 ms antes."""
        if landmarks is None:
            self._recentes.clear()
            return 0.0
        if self._recentes and timestamp_ms <= self._recentes[-1][0]:
            return self.velocidade  # quadro repetido ou fora de ordem
        self._recentes.append((timestamp_ms, _vetor_de_movimento(landmarks)))
        limite = timestamp_ms - JANELA_VELOCIDADE_MS * 2 - 200
        while self._recentes[0][0] < limite:
            self._recentes.popleft()
        recentes = list(self._recentes)
        # Último quadro que está a pelo menos uma janela de distância.
        antes = max(
            (i for i, (t, _) in enumerate(recentes) if t <= timestamp_ms - JANELA_VELOCIDADE_MS),
            default=None,
        )
        if antes is None:
            return 0.0
        grupo_agora = recentes[-QUADROS_NA_MEDIA:]
        grupo_antes = recentes[max(0, antes - QUADROS_NA_MEDIA + 1):antes + 1]
        dt = (
            np.mean([t for t, _ in grupo_agora]) - np.mean([t for t, _ in grupo_antes])
        ) / 1000
        if dt <= 0:
            return 0.0
        deslocamento = np.mean([v for _, v in grupo_agora], axis=0) - np.mean(
            [v for _, v in grupo_antes], axis=0
        )
        return float(np.linalg.norm(deslocamento)) / dt

    def observar(self, timestamp_ms, landmarks):
        """Devolve ``(inicio_ms, fim_ms)`` quando um movimento termina."""
        self.descartado_ms = None
        velocidade = self.velocidade = self._medir(timestamp_ms, landmarks)
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
