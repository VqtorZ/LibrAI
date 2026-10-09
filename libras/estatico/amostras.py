"""Amostras do alfabeto estático (``dados/amostras_estaticas/alfabeto.csv``).

Uma linha por amostra: a letra e as 63 coordenadas normalizadas da mão
(as features geométricas são recalculadas no treino). As amostras são
gravadas pelo site, com os pontos vindos da câmera do navegador.
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import threading
from collections import Counter

from ..caminhos import AMOSTRAS_ESTATICAS
from .features import extrair_features_de_valores

N_FEATURES = 63
CABECALHO = ["label"] + [f"f{i}" for i in range(N_FEATURES)]
# J e Z são reconhecidos pelo movimento (libras.movimento), não por aqui.
LETRAS_ESTATICAS = [letra for letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if letra not in "JZ"]

_lock = threading.Lock()
# Caracteres de fim de linha (o csv grava as linhas terminadas em CR+LF).
FIM_DE_LINHA = chr(13) + chr(10)


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


def id_da_linha(linha):
    """Parte principal da identificação: tirada do próprio conteúdo da amostra.

    Não depende da posição no arquivo — se alguém grava ou apaga outra
    amostra ao mesmo tempo, as demais continuam com o mesmo id.
    """
    return hashlib.sha1(linha.rstrip(FIM_DE_LINHA).encode("utf-8")).hexdigest()[:12]


class Ids:
    """Dá ids às linhas na ordem do arquivo: ``<conteúdo>-<n>``.

    Duas amostras idênticas (Espaço apertado duas vezes na mesma imagem da
    câmera) recebem ``-1`` e ``-2``: apagar uma não leva a outra junto.
    """

    def __init__(self):
        self.vistas = Counter()

    def __call__(self, linha):
        base = id_da_linha(linha)
        self.vistas[base] += 1
        return f"{base}-{self.vistas[base]}"


def listar(letra, caminho=None):
    """Amostras da letra, na ordem em que foram gravadas.

    Cada item: ``{"id", "numero", "valores"}`` (63 coordenadas relativas ao
    pulso, como ficam no arquivo).
    """
    letra = validar_letra(letra)
    caminho = _arquivo(caminho)
    amostras = []
    ids = Ids()
    try:
        with caminho.open(encoding="utf-8") as arquivo:
            next(arquivo, None)  # cabeçalho
            for linha in arquivo:
                partes = linha.rstrip(FIM_DE_LINHA).split(",")
                if partes[0].strip() != letra or len(partes) != N_FEATURES + 1:
                    continue
                try:
                    valores = [float(v) for v in partes[1:]]
                except ValueError:
                    continue
                amostras.append({"id": ids(linha), "numero": len(amostras) + 1, "valores": valores})
    except FileNotFoundError:
        pass
    return amostras


def apagar(letra, ids, caminho=None):
    """Apaga as amostras da letra com esses ids; devolve quantas saíram.

    Reescreve o arquivo num temporário e troca de uma vez (``os.replace``):
    uma falha no meio nunca deixa o CSV pela metade.
    """
    letra = validar_letra(letra)
    alvo = set(ids)
    if not alvo:
        return 0
    caminho = _arquivo(caminho)
    with _lock:
        try:
            # newline="": mantém a quebra de linha do csv (o "Desfazer última" compara bytes).
            with caminho.open(encoding="utf-8", newline="") as arquivo:
                linhas = arquivo.readlines()
        except FileNotFoundError:
            return 0
        if not linhas:
            return 0
        mantidas = [linhas[0]]
        apagadas = 0
        ids = Ids()
        for linha in linhas[1:]:
            if linha.split(",", 1)[0].strip() == letra and ids(linha) in alvo:
                apagadas += 1
            else:
                mantidas.append(linha)
        if apagadas:
            temporario = caminho.with_name(caminho.name + ".tmp")
            temporario.write_text("".join(mantidas), encoding="utf-8", newline="")
            os.replace(temporario, caminho)
    return apagadas

