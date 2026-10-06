"""Reconhecimento de movimentos ao vivo (Etapa 5).

Recebe, frame a frame, os landmarks crus da câmera do reconhecedor,
separa o trecho em que a mão se moveu (``temporal.Segmentador``) e,
quando a mão para, compara esse trecho com o modelo temporal. A
mesma segmentação recorta as amostras gravadas no treino, então
coleta e reconhecimento comparam trechos equivalentes.
"""
from __future__ import annotations

from collections import deque

from . import temporal

# Histórico mantido em memória (movimento mais longo + contexto).
HISTORICO_MS = temporal.DURACAO_MAX_MOVIMENTO_MS + 1000


class DetectorMovimento:
    """Segmenta movimentos ao vivo e os classifica com o modelo temporal."""

    def __init__(self, caminho_modelo=None):
        self._caminho = caminho_modelo
        self._modelo = None
        self._modelo_mtime = None
        self.erro = None
        self._historico = deque()
        self._segmentador = temporal.Segmentador()

    def _carregar(self):
        """(Re)carrega o modelo quando o arquivo muda; None se indisponível."""
        caminho = temporal._caminho(self._caminho)
        try:
            mtime = caminho.stat().st_mtime
        except OSError:
            self._modelo, self._modelo_mtime = None, None
            self.erro = "Modelo de movimentos ainda não treinado."
            return None
        if mtime != self._modelo_mtime:
            try:
                self._modelo = temporal.carregar_modelo(caminho)
                self.erro = None
            except temporal.ErroTemporal as exc:
                self._modelo = None
                self.erro = str(exc)
            self._modelo_mtime = mtime
        return self._modelo

    @property
    def pronto(self):
        return self._carregar() is not None

    def observar(self, timestamp_ms, landmarks=None, mao=None):
        """Registra um frame; devolve a previsão quando um movimento termina.

        ``landmarks`` são os 63 valores crus do MediaPipe (ou None sem
        mão). O retorno é o dicionário de ``temporal.prever`` com
        ``reconhecido`` True/False, ou None enquanto não há movimento
        completo para avaliar.
        """
        self._historico.append(
            {"timestamp_ms": timestamp_ms, "landmarks": landmarks, "mao": mao}
        )
        while self._historico[0]["timestamp_ms"] < timestamp_ms - HISTORICO_MS:
            self._historico.popleft()
        segmento = self._segmentador.observar(timestamp_ms, landmarks)
        if segmento is None:
            return None
        trecho = temporal.recortar(self._historico, *segmento)
        if sum(1 for f in trecho if f["landmarks"] is not None) < temporal.FRAMES_MIN_TRAJETORIA:
            return None
        modelo = self._carregar()
        if modelo is None:
            return None
        trajetoria = temporal.processar_frames(trecho)
        if len(trajetoria) < 2:
            return None
        return temporal.prever(trajetoria, modelo)
