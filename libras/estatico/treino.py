"""Treino do classificador do alfabeto estático (RandomForest).

Lê as amostras coletadas (``dados/amostras_estaticas/alfabeto.csv``),
acrescenta as features geométricas e salva o modelo em
``dados/modelos_treinados/alfabeto.joblib``. Usado pelo botão "Treinar
alfabeto" do site e pelo comando ``treinar_alfabeto``.

O modelo salvo guarda também QUAIS amostras ele aprendeu (os ids de
``estatico.amostras``), para o site mostrar o que é "treinada" e o que é
"nova", e as letras deixadas de fora de propósito.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

from ..caminhos import AMOSTRAS_ESTATICAS, MODELO_ALFABETO, salvar_modelo_atomico
from .amostras import Ids
from .classificador import FORMATO_ALFABETO
from .features import features_geometricas

COLUNAS_BASE = 63


class ErroTreino(Exception):
    """Dados insuficientes para treinar (mensagem vai ao terminal)."""


def montar_features(dados):
    """Reconstrói as 63 coords de cada amostra e acrescenta as features
    geométricas, mantendo consistência com extrair_features da câmera."""
    coords = dados[dados.columns[1:1 + COLUNAS_BASE]].to_numpy(dtype=float)
    geo = np.array([features_geometricas(linha) for linha in coords], dtype=float)
    return np.hstack([coords, geo])


def _ler_amostras(dataset, sem_letras):
    """Uma leitura só do arquivo: as linhas usadas e os ids de cada letra."""
    with dataset.open(encoding="utf-8", newline="") as arquivo:
        linhas = arquivo.readlines()
    if not linhas:
        return None, {}
    ids = Ids()
    usadas = [linhas[0]]
    por_letra = {}
    for linha in linhas[1:]:
        letra = linha.split(",", 1)[0].strip()
        if not letra:
            continue
        id_amostra = ids(linha)
        if letra in sem_letras:
            continue
        usadas.append(linha)
        por_letra.setdefault(letra, []).append(id_amostra)
    return pd.read_csv(io.StringIO("".join(usadas))), por_letra


def treinar(dataset=None, destino=None, sem_letras=()):
    """Treina e salva o modelo; devolve o relatório de classificação.

    ``sem_letras``: letras deixadas de fora deste modelo (as amostras delas
    continuam no arquivo e voltam no próximo treino normal).
    """
    dataset = dataset if dataset is not None else AMOSTRAS_ESTATICAS
    destino = destino if destino is not None else MODELO_ALFABETO
    sem_letras = {letra.strip().upper() for letra in sem_letras}
    if not dataset.exists():
        raise ErroTreino("Nenhuma amostra do alfabeto ainda. Grave as letras pelo site (Gestos → Gravar letras).")
    dados, por_letra = _ler_amostras(dataset, sem_letras)
    if dados is None or "label" not in dados or dados["label"].nunique() < 2:
        raise ErroTreino("Colete pelo menos duas letras antes de treinar.")
    if dados["label"].value_counts().min() < 2:
        raise ErroTreino("Cada letra precisa de pelo menos duas amostras.")
    X = montar_features(dados)
    y = dados["label"]
    X_treino, X_teste, y_treino, y_teste = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    modelo = RandomForestClassifier(
        n_estimators=400, class_weight="balanced", random_state=42, n_jobs=-1
    )
    modelo.fit(X_treino, y_treino)
    relatorio = classification_report(y_teste, modelo.predict(X_teste), zero_division=0)
    # A separação acima só mede o acerto; o modelo final aprende TODAS as
    # amostras (antes, 1 em cada 5 ficava de fora para sempre).
    modelo.fit(X, y)
    salvar_modelo_atomico(
        {
            "formato": FORMATO_ALFABETO,
            "treinado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "modelo": modelo,
            "amostras": por_letra,
            "letras_fora": sorted(sem_letras),
        },
        destino,
    )
    return relatorio
