"""Treina o classificador do alfabeto estático a partir do CSV coletado."""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from libras.vision import geometric_features


DATASET = Path("dataset/landmarks.csv")
MODEL = Path("models/libras_alphabet.joblib")
BASE_COLS = 63


def build_features(data):
    """Reconstrói as 63 coords de cada amostra e acrescenta as features
    geométricas, mantendo consistência com extract_features da visão."""
    coords = data[data.columns[1:1 + BASE_COLS]].to_numpy(dtype=float)
    geo = np.array([geometric_features(row) for row in coords], dtype=float)
    return np.hstack([coords, geo])


def main():
    if not DATASET.exists():
        raise SystemExit("Dataset ausente. Execute scripts/coletar_libras.py primeiro.")
    data = pd.read_csv(DATASET)
    if "label" not in data or data["label"].nunique() < 2:
        raise SystemExit("Colete pelo menos duas letras antes de treinar.")
    counts = data["label"].value_counts()
    if counts.min() < 2:
        raise SystemExit("Cada letra precisa de pelo menos duas amostras.")
    X = build_features(data)
    y = data["label"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    model = RandomForestClassifier(
        n_estimators=400, class_weight="balanced", random_state=42, n_jobs=-1
    )
    model.fit(X_train, y_train)
    print(classification_report(y_test, model.predict(X_test), zero_division=0))
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL)
    print(f"Modelo salvo em {MODEL}.")


if __name__ == "__main__":
    main()
