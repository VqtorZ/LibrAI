"""Como uma mão vira números para o classificador do alfabeto.

Usado na gravação pelo site (``estatico.amostras``), no treino (``estatico.treino``)
e no reconhecimento ao vivo (``estatico.classificador``) — os três precisam
gerar exatamente as mesmas features.
"""
from __future__ import annotations

# Pontas dos dedos: polegar, indicador, médio, anelar, mindinho.
PONTAS_DOS_DEDOS = [4, 8, 12, 16, 20]
# Articulações do indicador e do médio (meio, perto da ponta, ponta) e as
# bases dos dois dedos, usadas na medida de cruzamento (U × R).
INDICADOR = (6, 7, 8)
MEDIO = (10, 11, 12)
BASE_INDICADOR, BASE_MEDIO = 5, 9


def cruzamento_indicador_medio(points):
    """De que lado do médio está o indicador, em cada articulação.

    Mede no eixo que vai da base do médio à base do indicador: com os dedos
    lado a lado (U) o indicador continua "do lado dele" (valor ~ +0,8); com
    os dedos cruzados (R) as pontas ficam uma sobre a outra ou trocam de
    lado (valor ~ 0 ou negativo). Não depende de mão direita/esquerda nem
    do tamanho da mão. Medido nas amostras de 07/10: U sempre positivo
    (mediana +0,79), R em torno de zero; confusões U↔R de 7 para 1.
    """
    eixo = [b - m for b, m in zip(points[BASE_INDICADOR], points[BASE_MEDIO])]
    norma2 = sum(v * v for v in eixo) or 1.0
    return [
        sum((a - b) * e for a, b, e in zip(points[i], points[m], eixo)) / norma2
        for i, m in zip(INDICADOR, MEDIO)
    ]


def features_geometricas(coords):
    """Relevantes p/ distinguir letras parecidas (U × V, U × R).

    Recebe os 63 valores normalizados (21 marcos x, y, z relativos ao pulso)
    e retorna as distâncias entre as pontas dos dedos (abertura entre os
    dedos: U × V) e o cruzamento indicador/médio (U × R). Scale-invariante.
    As novas vão sempre no FIM: modelos antigos usam só as primeiras.
    """
    points = [coords[i * 3:(i + 1) * 3] for i in range(21)]

    def dist(a, b):
        return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5

    tips = [points[i] for i in PONTAS_DOS_DEDOS]
    features = []
    for i in range(len(tips)):
        for j in range(i + 1, len(tips)):
            features.append(dist(tips[i], tips[j]))
    return features + cruzamento_indicador_medio(points)


def extrair_features(landmarks):
    """Normaliza os 21 marcos em 63 coordenadas relativas ao pulso e
    acrescenta features geométricas para melhor separação U vs V."""
    wrist = landmarks[0]
    values = []
    for point in landmarks:
        values.extend((point.x - wrist.x, point.y - wrist.y, point.z - wrist.z))
    scale = max((abs(value) for value in values), default=1.0) or 1.0
    normalized = [value / scale for value in values]
    return normalized + features_geometricas(normalized)


class _Ponto:
    """Ponto com x, y, z — o formato que extrair_features espera."""

    __slots__ = ("x", "y", "z")

    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


def extrair_features_de_valores(valores):
    """Mesmo que extrair_features, a partir dos 63 valores crus (x, y, z)."""
    pontos = [_Ponto(*valores[i:i + 3]) for i in range(0, len(valores), 3)]
    return extrair_features(pontos)
