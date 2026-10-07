"""Frames crus → trajetória comparável (features do movimento).

Cada passo da trajetória tem a forma da mão (63 valores, relativos ao
pulso e à escala) e o deslocamento do pulso em tamanhos de mão (2
valores). Antes disso: lacunas interpoladas, mão esquerda espelhada e
reamostragem a passo fixo; depois, aparo do repouso nas pontas.
"""
from __future__ import annotations

import numpy as np

from .amostras import LANDMARKS_POR_MAO, VALORES_POR_LANDMARK

VALORES_POR_FRAME = LANDMARKS_POR_MAO * VALORES_POR_LANDMARK
# Forma (63) + deslocamento do pulso (x, y).
VALORES_POR_PASSO = VALORES_POR_FRAME + 2
# Passo da reamostragem (~15 fps, o mesmo da página de gravação).
INTERVALO_REAMOSTRAGEM_MS = 66
# Peso do deslocamento do pulso (em tamanhos de mão) frente à forma.
PESO_TRAJETORIA = 1.0
# Fração da velocidade máxima abaixo da qual as pontas são repouso.
FRACAO_REPOUSO = 0.15
# Menor trajetória aceita pelo aparo de repouso.
FRAMES_MIN_TRAJETORIA = 8


def normalizar_frame(landmarks):
    """63 valores crus → relativos ao pulso (landmark 0) e à escala.

    Mesma invariância de translação/escala adotada pelo pipeline
    estático, reimplementada aqui para que os dois pipelines sigam
    independentes — este módulo não importa nada do estático.
    """
    pontos = np.asarray(landmarks, dtype=float).reshape(LANDMARKS_POR_MAO, 3)
    pontos = pontos - pontos[0]
    escala = float(np.abs(pontos).max()) or 1.0
    return (pontos / escala).reshape(-1).tolist()


def _preencher_lacunas(frames):
    """Frames → (timestamps, landmarks crus, mãos) sem lacunas.

    Os frames vazios das pontas são truncados (a mão ainda não entrou /
    já saiu do quadro) e os do meio são interpolados linearmente por
    timestamp entre os vizinhos válidos — o padrão temporal é
    preservado sem descartar frames do meio do movimento.
    """
    validos = [i for i, f in enumerate(frames) if f["landmarks"] is not None]
    if not validos:
        return [], [], []
    tempos, crus, maos = [], [], []
    for indice in range(validos[0], validos[-1] + 1):
        frame = frames[indice]
        tempos.append(frame["timestamp_ms"])
        maos.append(frame.get("mao"))
        if frame["landmarks"] is not None:
            crus.append(list(frame["landmarks"]))
            continue
        anterior = max(v for v in validos if v < indice)
        proximo = min(v for v in validos if v > indice)
        fa, fb = frames[anterior], frames[proximo]
        ta, tb = fa["timestamp_ms"], fb["timestamp_ms"]
        peso = (frame["timestamp_ms"] - ta) / (tb - ta) if tb > ta else 0.0
        crus.append(
            [a + (b - a) * peso for a, b in zip(fa["landmarks"], fb["landmarks"])]
        )
    return tempos, crus, maos


def _reamostrar(tempos, vetores):
    """Interpola a sequência numa grade fixa de ``INTERVALO_REAMOSTRAGEM_MS``.

    Gravações (≈15 fps) e câmera ao vivo (≈30 fps) passam a ter o mesmo
    passo temporal, o que mantém as distâncias DTW comparáveis.
    """
    tempos = np.asarray(tempos, dtype=float)
    vetores = np.asarray(vetores, dtype=float)
    if len(tempos) < 2 or tempos[-1] <= tempos[0]:
        return vetores
    # Timestamps repetidos quebrariam a interpolação: mantém o primeiro.
    unicos = np.concatenate(([True], np.diff(tempos) > 0))
    tempos, vetores = tempos[unicos], vetores[unicos]
    grade = np.arange(tempos[0], tempos[-1] + 1e-9, INTERVALO_REAMOSTRAGEM_MS)
    return np.stack(
        [np.interp(grade, tempos, vetores[:, k]) for k in range(vetores.shape[1])],
        axis=1,
    )


def _aparar_repouso(vetores):
    """Remove a mão parada no início e no fim da sequência.

    A velocidade de cada passo é comparada à maior velocidade do
    gesto; trechos das pontas abaixo de ``FRACAO_REPOUSO`` dela são
    considerados espera, não sinal. Se sobrar pouco, nada é cortado.
    """
    if len(vetores) < FRAMES_MIN_TRAJETORIA:
        return vetores
    velocidade = np.linalg.norm(np.diff(vetores, axis=0), axis=1)
    suave = np.convolve(velocidade, np.ones(3) / 3, mode="same")
    pico = float(suave.max())
    if pico <= 0:
        return vetores
    ativos = np.flatnonzero(suave >= pico * FRACAO_REPOUSO)
    # velocidade[i] liga os frames i e i+1; a suavização já dá a folga.
    inicio = int(ativos[0])
    fim = int(ativos[-1]) + 1
    if fim - inicio + 1 < FRAMES_MIN_TRAJETORIA:
        return vetores
    return vetores[inicio:fim + 1]


def _espelhar(crus):
    """Espelha landmarks crus no eixo x (coordenadas de imagem 0..1)."""
    pontos = np.asarray(crus, dtype=float).reshape(len(crus), LANDMARKS_POR_MAO, 3)
    pontos[:, :, 0] = 1.0 - pontos[:, :, 0]
    return pontos.reshape(len(crus), -1)


def _mao_esquerda(maos):
    """Maioria dos frames rotulados como "Left" → sinal feito com a esquerda."""
    rotuladas = [m for m in maos if m is not None]
    return bool(rotuladas) and rotuladas.count("Left") > len(rotuladas) / 2


def processar_frames(frames):
    """Frames crus (``timestamp_ms``/``landmarks``/``mao``) → trajetória.

    Cada passo da trajetória tem ``VALORES_POR_PASSO`` valores:

    * 63 da **forma** da mão (``normalizar_frame``: relativos ao pulso
      e à escala) — captura giros e mudanças de configuração;
    * 2 do **deslocamento do pulso** (x, y) desde o início do gesto,
      medido em tamanhos de mão — captura sinais em que o braço
      desenha o movimento (como o Z), que a forma sozinha não vê.

    Antes disso, sinais feitos com a mão esquerda são espelhados e a
    sequência é reamostrada a passo fixo; ao final, o repouso das
    pontas é aparado.
    """
    tempos, crus, maos = _preencher_lacunas(frames)
    if not crus:
        return []
    crus = np.asarray(crus, dtype=float)
    if _mao_esquerda(maos):
        crus = _espelhar(crus)
    pontos = crus.reshape(len(crus), LANDMARKS_POR_MAO, 3)
    # Tamanho da mão: pulso (0) → base do dedo médio (9), mediana no tempo.
    tamanho = float(np.median(
        np.linalg.norm(pontos[:, 9, :2] - pontos[:, 0, :2], axis=1)
    )) or 1.0
    forma = np.array([normalizar_frame(f) for f in crus])
    pulso = pontos[:, 0, :2] / tamanho * PESO_TRAJETORIA
    passos = _aparar_repouso(_reamostrar(tempos, np.hstack([forma, pulso])))
    passos[:, -2:] -= passos[0, -2:]
    return passos.tolist()
