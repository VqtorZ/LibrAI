"""Reconhecimento ao vivo, uma sessão por aba do navegador.

O navegador detecta a mão (MediaPipe) e manda, em lotes, os quadros:
``{"t": ms, "marcos": [63 valores] ou null, "mao": "Right"/"Left"/null}``.
Cada aba tem um "canal" (um id aleatório) e, com ele, o seu próprio
detector de movimento — várias pessoas podem reconhecer ao mesmo tempo
sem uma interferir na outra. A letra parada é classificada no último
quadro do lote.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from . import segmentacao
from .ao_vivo import DetectorMovimento

# Por quanto tempo (no relógio do navegador) um movimento reconhecido fica na tela.
EXIBICAO_MOVIMENTO_MS = 2500
# "Analisando movimento…" só depois de o movimento durar isto: um tremor
# rápido (dedos escondidos no M, N, Q) não troca a letra pela mensagem.
MOSTRAR_ANALISANDO_APOS_MS = 300
ROTULO_ANALISANDO = "Analisando movimento…"
ROTULO_SEM_MAO = "Aguardando mão"
# Sessões paradas somem da memória; e há um teto de sessões simultâneas.
SESSAO_OCIOSA_S = 600
MAXIMO_SESSOES = 200


class SessaoAoVivo:
    def __init__(self):
        self.detector = DetectorMovimento()
        self.movimento_label = None
        self.movimento_ate = 0
        self.ultimo_t = None
        self.usada_em = time.monotonic()
        self.lock = threading.Lock()

    def processar(self, quadros, classificador_alfabeto):
        """Alimenta o detector com o lote e devolve o estado para a tela."""
        with self.lock:
            self.usada_em = time.monotonic()
            for quadro in quadros:
                t = quadro["timestamp_ms"]
                if self.ultimo_t is not None and t < self.ultimo_t:
                    continue  # quadro fora de ordem: ignora
                self.ultimo_t = t
                previsao = self.detector.observar(t, quadro["landmarks"], quadro["mao"])
                if previsao and previsao["reconhecido"]:
                    self.movimento_label = previsao["previsto"]
                    self.movimento_ate = t + EXIBICAO_MOVIMENTO_MS
            ultimo = quadros[-1]
            if self.ultimo_t is not None and self.ultimo_t >= self.movimento_ate:
                self.movimento_label = None
            mao = ultimo["landmarks"] is not None
            if self.movimento_label:
                rotulo = self.movimento_label
            elif self._analisando():
                rotulo = ROTULO_ANALISANDO
            elif mao:
                rotulo = classificador_alfabeto.classificar(ultimo["landmarks"])
            else:
                rotulo = ROTULO_SEM_MAO
            return {
                "label": rotulo,
                "movement_label": self.movimento_label,
                "hand_detected": mao,
                "model_ready": classificador_alfabeto.pronto,
                "movement_ready": self.detector.pronto,
                # Modo diagnóstico (?diagnostico=1): velocidade × limite.
                "movement_speed": round(self.detector.velocidade, 2),
                "movement_limit": segmentacao.VELOCIDADE_INICIO,
            }

    def _analisando(self):
        inicio = self.detector.inicio_movimento_ms
        return (
            self.detector.em_movimento
            and self.detector.pronto
            and inicio is not None
            and self.ultimo_t - inicio >= MOSTRAR_ANALISANDO_APOS_MS
        )


_sessoes: "OrderedDict[str, SessaoAoVivo]" = OrderedDict()
_lock = threading.Lock()


def sessao(canal):
    """Sessão do canal (criada na primeira vez); limpa as abandonadas."""
    agora = time.monotonic()
    with _lock:
        for chave in [c for c, s in _sessoes.items() if agora - s.usada_em > SESSAO_OCIOSA_S]:
            del _sessoes[chave]
        atual = _sessoes.pop(canal, None) or SessaoAoVivo()
        _sessoes[canal] = atual  # mais recente no fim
        while len(_sessoes) > MAXIMO_SESSOES:
            _sessoes.popitem(last=False)
        return atual


def limpar():
    """Esquece todas as sessões (usado nos testes)."""
    with _lock:
        _sessoes.clear()
