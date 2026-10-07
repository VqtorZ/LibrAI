"""Treino do classificador do alfabeto estático (RandomForest).

Lê as amostras coletadas (``dados/amostras_estaticas/landmarks.csv``),
acrescenta as features geométricas e salva o modelo em
``dados/modelos_treinados/alfabeto.joblib``. Usado pelo comando
``treinar_alfabeto``.
"""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

from ..caminhos import AMOSTRAS_ESTATICAS, COMPRESSAO_MODELOS, MODELO_ALFABETO
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


def treinar(dataset=AMOSTRAS_ESTATICAS, destino=MODELO_ALFABETO):
    """Treina e salva o modelo; devolve o relatório de classificação."""
    if not dataset.exists():
        raise ErroTreino("Dataset ausente. Colete amostras com: python manage.py coletar_alfabeto <letra>")
    dados = pd.read_csv(dataset)
    if "label" not in dados or dados["label"].nunique() < 2:
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
    destino.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, destino, compress=COMPRESSAO_MODELOS)
    return relatorio
