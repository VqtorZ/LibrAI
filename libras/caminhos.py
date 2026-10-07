"""Onde ficam os dados do projeto — fonte única dos caminhos.

Tudo que é dado mora em ``dados/``:

* ``banco.sqlite3`` — banco do Django (sinais e o registro das amostras);
  fora do Git;
* ``amostras_estaticas/landmarks.csv`` — amostras do alfabeto estático,
  uma linha por amostra (letra + 63 coordenadas);
* ``amostras_movimento/<id>-<sinal>/<amostra>.json`` — pontos da mão de
  cada amostra de movimento, frame a frame; fora do Git;
* ``modelos_treinados/`` — modelos gerados pelos treinos;
* ``sinteticos/`` — dados artificiais de teste (nunca entram no treino).

Módulo sem dependência do Django: as configurações (``config/settings.py``)
também o usam.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"

BANCO = DADOS / "banco.sqlite3"
AMOSTRAS_ESTATICAS = DADOS / "amostras_estaticas" / "landmarks.csv"
AMOSTRAS_MOVIMENTO = DADOS / "amostras_movimento"
SINTETICOS = DADOS / "sinteticos"

MODELOS_TREINADOS = DADOS / "modelos_treinados"
MODELO_ALFABETO = MODELOS_TREINADOS / "alfabeto.joblib"
MODELO_MOVIMENTOS = MODELOS_TREINADOS / "movimentos.joblib"

# Compressão dos modelos salvos: o RandomForest do alfabeto passava de 40 MB.
COMPRESSAO_MODELOS = 3
