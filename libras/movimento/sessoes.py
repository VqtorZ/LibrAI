"""Reconhecimento ao vivo, uma sessão por aba do navegador.

O navegador detecta a mão (MediaPipe) e manda, em lotes, os quadros:
``{"t": ms, "marcos": [63 valores] ou null, "mao": "Right"/"Left"/null}``.
Cada aba tem um "canal" (um id aleatório) e, com ele, o seu próprio
detector de movimento — várias pessoas podem reconhecer ao mesmo tempo
sem uma interferir na outra. A letra parada é classificada no último
quadro do lote.
"""
from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque

from ..estatico.classificador import NAO_IDENTIFICADO, SEM_MODELO
from . import segmentacao
from .ao_vivo import DetectorMovimento

# Por quanto tempo (no relógio do navegador) um movimento reconhecido fica na tela.
EXIBICAO_MOVIMENTO_MS = 2500
# "Analisando movimento…" só depois de o movimento durar isto: um tremor
# rápido (dedos escondidos no M, N, Q) não troca a letra pela mensagem.
MOSTRAR_ANALISANDO_APOS_MS = 300
# Tremor de mão parada (o M, com três dedos escondidos, treme mais que o
# filtro do segmentador segura): o pulso não sai do lugar E a letra parada
# continua a mesma, com confiança alta, o movimento inteiro. Aí não é
# movimento: a tela mantém a letra e o resultado do movimento é ignorado.
# Nas 76 gravações reais de J, o pulso andou no mínimo 0,44 tamanho de mão
# e em nenhuma a letra parada ficou firme o movimento todo — bloquearia 0.
PULSO_PARADO_TAMANHOS = 0.3
CONFIANCA_LETRA_FIRME = 0.8
# A letra parada é decidida pela média das imagens com mão dos últimos
# ~200 ms (não por uma imagem só): uma imagem ruim não troca a letra.
JANELA_VOTACAO_MS = 200
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
        self._recentes = deque()  # (t, marcos) das imagens com mão, ~200 ms
        self._zerar_acompanhamento()

    def _guardar_para_votacao(self, quadro):
        if quadro["landmarks"] is None:
            self._recentes.clear()  # a mão saiu: a próxima letra começa do zero
            return
        t = quadro["timestamp_ms"]
        self._recentes.append((t, quadro["landmarks"]))
        while self._recentes[0][0] < t - JANELA_VOTACAO_MS:
            self._recentes.popleft()

    def _letra_parada(self, classificador_alfabeto):
        """Letra parada pela média das imagens recentes (ou da última, se não der)."""
        marcos = [m for _, m in self._recentes]
        media = getattr(classificador_alfabeto, "classificar_media", None)
        if media is not None:
            return media(marcos)
        return classificador_alfabeto.classificar_com_confianca(marcos[-1])

    # --- acompanhamento do movimento em andamento (tremor × movimento) ------
    def _zerar_acompanhamento(self):
        self._mov_inicio = None      # início do movimento acompanhado
        self._pulso_inicial = None   # (x, y) do pulso quando ele começou
        self._tamanho_mao = 1.0
        self._pulso_andou = 0.0      # máximo, em tamanhos de mão
        self._letras = []            # (letra parada, confiança) durante ele

    def _acompanhar(self, quadro):
        inicio = self.detector.inicio_movimento_ms
        marcos = quadro["landmarks"]
        if inicio is None or marcos is None:
            return
        if inicio != self._mov_inicio:
            self._zerar_acompanhamento()
            self._mov_inicio = inicio
            self._pulso_inicial = (marcos[0], marcos[1])
            self._tamanho_mao = math.hypot(marcos[27] - marcos[0], marcos[28] - marcos[1]) or 1.0
            return
        x0, y0 = self._pulso_inicial
        andou = math.hypot(marcos[0] - x0, marcos[1] - y0) / self._tamanho_mao
        self._pulso_andou = max(self._pulso_andou, andou)

    def _foi_tremor(self):
        """A mão "se moveu" sem sair do lugar e sem mudar de letra parada."""
        if self._mov_inicio is None or not self._letras:
            return False
        primeira = self._letras[0][0]
        return (
            self._pulso_andou < PULSO_PARADO_TAMANHOS
            and primeira not in (SEM_MODELO, NAO_IDENTIFICADO)
            and all(letra == primeira and c >= CONFIANCA_LETRA_FIRME for letra, c in self._letras)
        )

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
                self._acompanhar(quadro)
                self._guardar_para_votacao(quadro)
                if previsao is not None:
                    if previsao["reconhecido"] and not self._foi_tremor():
                        self.movimento_label = previsao["previsto"]
                        self.movimento_ate = t + EXIBICAO_MOVIMENTO_MS
                    self._zerar_acompanhamento()
                elif not self.detector.em_movimento:
                    self._zerar_acompanhamento()
            ultimo = quadros[-1]
            if self.ultimo_t is not None and self.ultimo_t >= self.movimento_ate:
                self.movimento_label = None
            mao = ultimo["landmarks"] is not None
            letra, confianca = self._letra_parada(classificador_alfabeto) if mao else (None, 0.0)
            if mao and self._mov_inicio is not None:
                self._letras.append((letra, confianca))
            if self.movimento_label:
                rotulo = self.movimento_label
            elif self._analisando() and not self._foi_tremor():
                rotulo = ROTULO_ANALISANDO
            elif mao:
                rotulo = letra
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
        """Mostrar "Analisando movimento…"? Só se a mão anda DE VERDADE.

        Trocar de uma letra parada para outra mexe os dedos (o segmentador
        vê "movimento"), mas o pulso quase não sai do lugar: nesse caso a
        letra nova aparece direto. Os sinais de movimento (J, Z…) andam o
        pulso bem mais que isso (no mínimo 0,44 tamanho de mão no J).
        Simulação com o modelo real: "Analisando" no meio de trocas de letra
        caiu de 7/48 para 0/48.
        """
        inicio = self.detector.inicio_movimento_ms
        return (
            self.detector.em_movimento
            and self.detector.pronto
            and inicio is not None
            and self.ultimo_t - inicio >= MOSTRAR_ANALISANDO_APOS_MS
            and self._pulso_andou >= PULSO_PARADO_TAMANHOS
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
