"""Amostras do alfabeto estático (``dados/amostras_estaticas/landmarks.csv``).

Uma linha por amostra: a letra e as 63 coordenadas normalizadas da mão
(as features geométricas são recalculadas no treino). Usado pela página
de gravação do alfabeto no site; o comando ``coletar_alfabeto`` escreve
no mesmo formato.
"""
from __future__ import annotations

import csv
import io
import threading
from collections import Counter

from ..caminhos import AMOSTRAS_ESTATICAS
from .features import extrair_features_de_valores

N_FEATURES = 63
CABECALHO = ["label"] + [f"f{i}" for i in range(N_FEATURES)]
# J e Z são reconhecidos pelo movimento (libras.movimento), não por aqui.
LETRAS_ESTATICAS = [letra for letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if letra not in "JZ"]

_lock = threading.Lock()


class AmostraEstaticaInvalida(Exception):
    """Pedido de amostra do alfabeto que não pode ser atendido."""


def validar_letra(letra):
    letra = (letra or "").strip().upper()
    if letra not in LETRAS_ESTATICAS:
        raise AmostraEstaticaInvalida(
            "Escolha uma letra do alfabeto estático (J e Z são gravados como movimento)."
        )
    return letra


def _arquivo(caminho):
    # Lido na hora da chamada (não como valor padrão), para os testes
    # poderem redirecionar o arquivo e nunca tocarem nos dados reais.
    return caminho if caminho is not None else AMOSTRAS_ESTATICAS


def contar(caminho=None):
    """Quantidade de amostras por letra (sem carregar o CSV inteiro em memória)."""
    caminho = _arquivo(caminho)
    contagem = Counter()
    try:
        with caminho.open(encoding="utf-8") as arquivo:
            next(arquivo, None)  # cabeçalho
            for linha in arquivo:
                letra = linha.split(",", 1)[0].strip()
                if letra:
                    contagem[letra] += 1
    except FileNotFoundError:
        pass
    return dict(contagem)


def _linha_csv(valores):
    buffer = io.StringIO()
    csv.writer(buffer).writerow(valores)
    return buffer.getvalue()


def salvar(letra, landmarks, caminho=None):
    """Acrescenta uma amostra da letra; devolve a linha escrita (para desfazer).

    ``landmarks`` são os 63 valores crus do MediaPipe (x, y, z por ponto).
    """
    letra = validar_letra(letra)
    if landmarks is None or len(landmarks) != N_FEATURES:
        raise AmostraEstaticaInvalida("Posicione a mão na câmera antes de salvar.")
    caminho = _arquivo(caminho)
    features = extrair_features_de_valores(landmarks)[:N_FEATURES]
    linha = _linha_csv([letra, *features])
    with _lock:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        novo = not caminho.exists() or caminho.stat().st_size == 0
        with caminho.open("a", newline="", encoding="utf-8") as arquivo:
            if novo:
                arquivo.write(_linha_csv(CABECALHO))
            arquivo.write(linha)
    return linha


def desfazer(linha, caminho=None):
    """Remove a última amostra salva, se ela ainda for a última do arquivo."""
    if not linha:
        return False
    caminho = _arquivo(caminho)
    alvo = linha.encode("utf-8")
    with _lock:
        try:
            conteudo = caminho.read_bytes()
        except FileNotFoundError:
            return False
        if not conteudo.endswith(alvo):
            return False
        with caminho.open("r+b") as arquivo:
            arquivo.truncate(len(conteudo) - len(alvo))
    return True
