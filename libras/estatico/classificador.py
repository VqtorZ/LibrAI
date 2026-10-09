"""Classificador do alfabeto em uso no reconhecimento ao vivo.

O navegador manda os 63 valores da mão; aqui eles viram features e o
RandomForest diz a letra. O modelo é recarregado sozinho quando o
arquivo muda (retreino pelo site ou pelo comando) e só é aceito no
formato atual: modelos do tempo da câmera do servidor são ignorados,
porque os pontos daquela época foram medidos de outro jeito.
"""
from __future__ import annotations

import threading
import time

import joblib

from .. import caminhos
from .features import extrair_features_de_valores

# Formato 3: pontos vindos do navegador (MediaPipe Tasks), com x e z
# corrigidos pela proporção da imagem. Modelos salvos como dicionário.
FORMATO_ALFABETO = 3
LIMIAR_CONFIANCA = 0.70
INTERVALO_CONFERIR_S = 2.0

SEM_MODELO = "Modelo não treinado"
NAO_IDENTIFICADO = "Sinal não identificado"


class ClassificadorAlfabeto:
    def __init__(self, caminho=None):
        self._caminho = caminho
        self._lock = threading.Lock()
        self.modelo = None
        self._letras = []
        self.erro = None
        # Do último treino: ids das amostras aprendidas por letra (None se o
        # modelo é anterior a esse registro), quando e letras deixadas de fora.
        self.amostras_treinadas = None
        self.treinado_em = None
        self.letras_fora = []
        self._mtime = None
        self._conferido_em = None

    def _arquivo(self):
        return self._caminho if self._caminho is not None else caminhos.MODELO_ALFABETO

    def _carregar(self):
        self.modelo, self._letras, self.erro = None, [], None
        self.amostras_treinadas, self.treinado_em, self.letras_fora = None, None, []
        arquivo = self._arquivo()
        try:
            self._mtime = arquivo.stat().st_mtime
        except OSError:
            self._mtime = None
            return
        try:
            dados = joblib.load(arquivo)
        except (OSError, ValueError, ImportError, EOFError) as exc:
            self.erro = f"Não foi possível carregar o modelo do alfabeto: {exc}"
            return
        if not isinstance(dados, dict) or dados.get("formato") != FORMATO_ALFABETO:
            self.erro = "O modelo do alfabeto é de uma versão antiga — treine novamente."
            return
        modelo = dados["modelo"]
        if hasattr(modelo, "n_jobs"):
            # Para uma mão por vez, paralelizar custa mais que economiza.
            modelo.n_jobs = 1
        self.modelo = modelo
        self._letras = [str(c) for c in modelo.classes_]
        self.amostras_treinadas = dados.get("amostras")
        self.treinado_em = dados.get("treinado_em")
        self.letras_fora = list(dados.get("letras_fora", []))

    def conferir(self, agora_mesmo=False):
        """Recarrega o modelo se o arquivo mudou (no máximo a cada 2 s).

        ``agora_mesmo`` ignora o intervalo (páginas que mostram o treino
        logo depois de treinar).
        """
        agora = time.monotonic()
        with self._lock:
            if (not agora_mesmo and self._conferido_em is not None
                    and agora - self._conferido_em < INTERVALO_CONFERIR_S):
                return
            self._conferido_em = agora
            arquivo = self._arquivo()
            try:
                mtime = arquivo.stat().st_mtime
            except OSError:
                mtime = None
            if mtime != self._mtime or (mtime is None and self.modelo is not None):
                self._carregar()

    @property
    def pronto(self):
        self.conferir()
        return self.modelo is not None

    @property
    def letras(self):
        """Letras que o modelo atual reconhece (vazio sem modelo)."""
        self.conferir()
        return list(self._letras)

    def classificar(self, marcos):
        """Letra reconhecida para os 63 valores da mão (ou um aviso)."""
        self.conferir()
        modelo = self.modelo
        if modelo is None:
            return SEM_MODELO
        features = extrair_features_de_valores(marcos)
        # Modelo treinado antes de uma medida nova: usa só as que ele conhece
        # (as novas sempre vão no fim da lista).
        esperadas = getattr(modelo, "n_features_in_", len(features))
        features = [features[:esperadas]]
        try:
            probabilidades = modelo.predict_proba(features)[0]
        except (AttributeError, IndexError, ValueError) as exc:
            self.erro = f"Modelo do alfabeto inválido: {exc}"
            return SEM_MODELO
        indice = int(probabilidades.argmax())
        if float(probabilidades[indice]) < LIMIAR_CONFIANCA:
            return NAO_IDENTIFICADO
        return str(modelo.classes_[indice])


alfabeto = ClassificadorAlfabeto()
