"""Leitura dos marcos da mão a partir do resultado do MediaPipe.

Módulo sem dependência do Django: é usado pelo reconhecimento ao vivo
(``libras.captura.camera``), pela gravação de amostras de movimento
(``libras.movimento``) e pelo comando gravar_movimento,
para que todos extraiam os mesmos valores do mesmo jeito.
"""
MAOS_VALIDAS = ("Right", "Left")


def lateralidade(resultado):
    """"Right"/"Left" da primeira mão detectada, ou None se indisponível."""
    try:
        rotulo = resultado.multi_handedness[0].classification[0].label
    except (AttributeError, IndexError, TypeError):
        return None
    return rotulo if rotulo in MAOS_VALIDAS else None


def marcos_da_mao(resultado):
    """(63 valores crus x/y/z, mão) da primeira mão, ou (None, None)."""
    maos = getattr(resultado, "multi_hand_landmarks", None)
    if not maos:
        return None, None
    valores = [
        float(valor)
        for ponto in maos[0].landmark
        for valor in (ponto.x, ponto.y, ponto.z)
    ]
    return valores, lateralidade(resultado)
