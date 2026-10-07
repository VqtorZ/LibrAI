"""Pipeline temporal experimental (Etapa 4.2).

Primeiro protótipo de reconhecimento de movimentos a partir das
amostras gravadas pela coleta temporal (``libras.movimentos``):

1. validação estrutural reaproveitada da Etapa 4.1
   (``libras.verificacao.verificar_amostra``);
2. conversão dos frames em uma trajetória (``processar_frames``):
   forma da mão relativa ao pulso + deslocamento do pulso em tamanhos
   de mão, com espelhamento da mão esquerda, reamostragem a passo
   fixo e aparo do repouso nas pontas;
3. classificador DTW (Dynamic Time Warping) de vizinho mais próximo,
   com limiar de rejeição calibrado por leave-one-out intra-classe.

Com uma única classe e poucas amostras, isso demonstra que o pipeline
processa e reproduz o padrão gravado — não que diferencia sinais.
Os comandos de treinamento e teste declaram essa limitação.

Totalmente separado do pipeline estático: nada aqui altera o
RandomForest, ``libras/vision.py`` ou a página ``/reconhecer/``.
"""
from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from .caminhos import COMPRESSAO_MODELOS, MODELO_MOVIMENTOS
from .models import AmostraMovimento, Sinal
from .movimentos import LANDMARKS_POR_MAO, VALORES_POR_LANDMARK, ler_sequencia
from .verificacao import verificar_amostra, verificar_conteudo

MODELO_PATH = MODELO_MOVIMENTOS
# Formato 2: features com deslocamento do pulso, espelhamento,
# reamostragem e aparo de repouso (ver ``processar_frames``).
FORMATO_MODELO = 2
# Fator de segurança sobre a distância leave-one-out TÍPICA (mediana)
# da classe. Com as gravações reais de J, mediana × 1.5 aceitou todos
# os J em avaliação honesta e rejeitou J invertido, mão parada e Z
# simulado; o máximo × 2.0 anterior chegava a aceitar mão parada,
# porque um único par de amostras distantes estourava o limiar.
# Exemplos negativos apertam o limiar no treino.
MARGEM_LIMIAR = 1.5
# Piso do limiar: evita aceitar tudo quando amostras são idênticas.
LIMIAR_MINIMO = 0.05
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

# Segmentação de movimentos (``Segmentador``), calibrada com as
# gravações reais de J: mão em repouso fica em ~1–3,5 unidades/s
# (tremor natural) e o movimento do sinal em ~8–25 (unidades = forma
# normalizada + pulso em tamanhos de mão, por segundo).
VELOCIDADE_INICIO = 6.0      # média de 3 frames que inicia um movimento
VELOCIDADE_REPOUSO = 4.0     # abaixo disto a mão está parada
PAUSA_MS = 350               # tempo parado (ou sem mão) que encerra
PRE_MOVIMENTO_MS = 300       # contexto anterior incluído no trecho
DURACAO_MIN_MOVIMENTO_MS = 400
DURACAO_MAX_MOVIMENTO_MS = 4000


class ErroTemporal(Exception):
    """Falha esperada do pipeline temporal (mensagem vai ao terminal)."""


@dataclass
class TreinoResultado:
    """Saída do treino para o comando relatar."""

    modelo: dict
    trajetorias: list = field(default_factory=list)  # (pk, brutos, processados)
    invalidas: list = field(default_factory=list)    # (amostra, ResultadoVerificacao)
    excluidas: list = field(default_factory=list)    # (título da classe, amostras)


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


def _vetor_de_movimento(landmarks):
    """Forma normalizada + pulso em tamanhos de mão de um único frame."""
    pontos = np.asarray(landmarks, dtype=float).reshape(LANDMARKS_POR_MAO, 3)
    tamanho = float(np.linalg.norm(pontos[9, :2] - pontos[0, :2])) or 1.0
    return np.concatenate([normalizar_frame(landmarks), pontos[0, :2] / tamanho])


class Segmentador:
    """Detecta, frame a frame, onde um movimento começa e termina.

    O movimento começa quando a velocidade média (3 frames) passa de
    ``VELOCIDADE_INICIO`` e termina após ``PAUSA_MS`` com a mão parada
    ou fora do quadro (ou ao atingir ``DURACAO_MAX_MOVIMENTO_MS``).
    É usado ao vivo (``libras.ao_vivo``) e, no treino, para recortar
    as gravações — os dois lados comparam trechos equivalentes.
    """

    def __init__(self):
        self._anterior = None  # (timestamp_ms, vetor) do último frame com mão
        self._velocidades = deque(maxlen=3)
        self._inicio = None
        self._ultimo_movimento = None
        # Duração do último movimento descartado por ser curto (diagnóstico).
        self.descartado_ms = None

    @property
    def em_movimento(self):
        return self._inicio is not None

    def observar(self, timestamp_ms, landmarks):
        """Devolve ``(inicio_ms, fim_ms)`` quando um movimento termina."""
        self.descartado_ms = None
        if landmarks is None:
            self._anterior = None
            self._velocidades.clear()
        else:
            vetor = _vetor_de_movimento(landmarks)
            if self._anterior is not None:
                t_anterior, v_anterior = self._anterior
                dt = (timestamp_ms - t_anterior) / 1000
                if dt > 0:
                    self._velocidades.append(
                        float(np.linalg.norm(vetor - v_anterior)) / dt
                    )
            self._anterior = (timestamp_ms, vetor)
        velocidade = (
            sum(self._velocidades) / len(self._velocidades)
            if self._velocidades else 0.0
        )
        if self._inicio is None:
            if velocidade >= VELOCIDADE_INICIO:
                self._inicio = self._ultimo_movimento = timestamp_ms
            return None
        if landmarks is not None and velocidade >= VELOCIDADE_REPOUSO:
            self._ultimo_movimento = timestamp_ms
        parado = timestamp_ms - self._ultimo_movimento >= PAUSA_MS
        longo = timestamp_ms - self._inicio >= DURACAO_MAX_MOVIMENTO_MS
        if parado or longo:
            return self._fechar()
        return None

    def encerrar(self):
        """Fecha o movimento em aberto (fim de uma gravação)."""
        return self._fechar() if self._inicio is not None else None

    def _fechar(self):
        inicio, fim = self._inicio, self._ultimo_movimento
        self._inicio = self._ultimo_movimento = None
        # A duração mínima vale para o movimento em si, sem o contexto.
        if fim - inicio < DURACAO_MIN_MOVIMENTO_MS:
            self.descartado_ms = fim - inicio
            return None
        return inicio, fim


def recortar(frames, inicio, fim):
    """Frames do movimento ``(inicio, fim)`` mais o contexto anterior."""
    return [
        f for f in frames
        if inicio - PRE_MOVIMENTO_MS <= f["timestamp_ms"] <= fim
    ]


def segmentos(frames):
    """Todos os movimentos ``(inicio_ms, fim_ms)`` de uma gravação."""
    segmentador = Segmentador()
    encontrados = []
    for frame in frames:
        segmento = segmentador.observar(frame["timestamp_ms"], frame["landmarks"])
        if segmento:
            encontrados.append(segmento)
    final = segmentador.encerrar()
    if final:
        encontrados.append(final)
    return encontrados


def trecho_principal(frames):
    """Recorta o movimento mais longo da gravação.

    Descarta o que não é o sinal: a mão entrando no quadro logo após
    "Iniciar gravação" e saindo para clicar em "Parar" — movimentos
    curtos que, ao vivo, o reconhecedor nunca veria junto do sinal.
    Sem nenhum movimento detectado, a gravação inteira é usada.
    """
    encontrados = segmentos(frames)
    if not encontrados:
        return frames
    inicio, fim = max(encontrados, key=lambda s: s[1] - s[0])
    return recortar(frames, inicio, fim)


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


def processar_sequencia(conteudo):
    """JSON da amostra → trajetória do movimento principal gravado."""
    return processar_frames(trecho_principal(conteudo["frames"]))


def carregar_sequencia(amostra):
    """Valida (Etapa 4.1) e converte uma amostra em trajetória.

    Retorna ``(trajetoria, resultado_da_verificacao)``; a trajetória
    é ``None`` quando a amostra não passa no verificador.
    """
    resultado = verificar_amostra(amostra)
    if not resultado.ok:
        return None, resultado
    return processar_sequencia(ler_sequencia(amostra)), resultado


def distancia_dtw(a, b):
    """Distância DTW média por passo entre duas trajetórias.

    O custo local é a distância euclidiana entre frames normalizados;
    o alinhamento elástico absorve diferenças de ritmo entre
    gravações. A divisão por ``max(len)`` mantém a distância
    comparável entre sequências de comprimentos diferentes.
    """
    n, m = len(a), len(b)
    if not n or not m:
        return math.inf
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    custo = np.linalg.norm(x[:, None, :] - y[None, :, :], axis=2)
    acumulado = np.full((n + 1, m + 1), math.inf)
    acumulado[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            acumulado[i, j] = custo[i - 1, j - 1] + min(
                acumulado[i - 1, j - 1], acumulado[i - 1, j], acumulado[i, j - 1]
            )
    return float(acumulado[n, m] / max(n, m))


def preparar_amostras():
    """Amostras ativas de sinais de movimento, validadas e processadas.

    Retorna ``[(amostra, trajetoria_ou_None, resultado_verificacao)]``.
    """
    pares = []
    sinais = Sinal.objects.filter(tipo=Sinal.Tipo.MOVIMENTO, ativo=True).order_by("pk")
    for sinal in sinais:
        for amostra in sinal.amostras.filter(ativo=True):
            trajetoria, resultado = carregar_sequencia(amostra)
            pares.append((amostra, trajetoria, resultado))
    return pares


def _loo(entradas):
    """Leave-one-out intra-classe: [(pk, vizinho_pk, distância)]."""
    resultado = []
    for indice, (pk, trajetoria) in enumerate(entradas):
        vizinhos = [(v, t) for j, (v, t) in enumerate(entradas) if j != indice]
        distancia, vizinho = min(
            (distancia_dtw(trajetoria, t), v) for v, t in vizinhos
        )
        resultado.append((pk, vizinho, distancia))
    return resultado


def _tipica(distancias):
    """Distância leave-one-out típica (mediana) da classe."""
    return float(np.median([d for _, _, d in distancias])) if distancias else 0.0


def _limiar_de(distancias):
    return max(_tipica(distancias) * MARGEM_LIMIAR, LIMIAR_MINIMO)


def _negativo_mais_proximo(negativos, entradas):
    """Menor distância entre um exemplo negativo e os templates da classe."""
    if not negativos or not entradas:
        return None
    return min(
        distancia_dtw(negativo, template)
        for _, negativo in negativos
        for _, template in entradas
    )


def _calibrar(entradas, negativos):
    """Leave-one-out + limiar da classe, apertado pelos exemplos negativos.

    Sem negativos, o limiar é a distância LOO típica vezes a margem.
    Com negativos, ele também não passa do ponto médio entre essa
    distância e o negativo mais parecido — o modelo aprende onde a
    classe termina. Se algum negativo fica tão perto quanto os
    próprios exemplos da classe (sobreposição), o limiar volta à
    distância típica: aceitar os exemplos reais tem prioridade, e a
    regra do vizinho negativo em ``prever`` cuida do resto.
    """
    loo = _loo(entradas)
    tipica = _tipica(loo)
    limiar = _limiar_de(loo)
    negativo_min = _negativo_mais_proximo(negativos, entradas)
    sobreposicao = negativo_min is not None and negativo_min <= tipica
    if negativo_min is not None:
        teto = tipica if sobreposicao else (tipica + negativo_min) / 2
        limiar = max(min(limiar, teto), LIMIAR_MINIMO)
    return {
        "loo": loo,
        "limiar": limiar,
        "negativo_min": negativo_min,
        "sobreposicao": sobreposicao,
    }


def _caminho(caminho):
    return Path(caminho) if caminho is not None else MODELO_PATH


def treinar(caminho=None):
    """Treina o protótipo: memoriza trajetórias e calibra limiares.

    O limiar de cada classe parte da distância leave-one-out típica
    (mediana) intra-classe vezes ``MARGEM_LIMIAR`` e é apertado pelos sinais
    marcados como exemplo negativo (``Sinal.negativo``), cujas
    amostras também viram templates "de rejeição" (ver ``_calibrar``
    e ``prever``). Classes com menos de duas amostras ficam de fora
    (não há como calibrar o limiar).
    """
    destino = _caminho(caminho)
    pares = preparar_amostras()
    validas = [(a, t) for a, t, r in pares if t is not None]
    invalidas = [(a, r) for a, t, r in pares if t is None]
    if not validas:
        raise ErroTemporal(
            "Nenhuma amostra válida para treinar. Grave amostras e rode "
            "verificar_movimentos para diagnosticar a coleta."
        )
    trajetorias = [
        (amostra.pk, resultado.total_frames, len(trajetoria))
        for amostra, trajetoria, resultado in pares
        if trajetoria is not None
    ]
    classes = {}
    sinal_ids = {}
    negativos = []
    for amostra, trajetoria in validas:
        if amostra.sinal.negativo:
            negativos.append((amostra, trajetoria))
            continue
        classes.setdefault(amostra.sinal.titulo, []).append(
            (amostra.pk, trajetoria)
        )
        sinal_ids.setdefault(amostra.sinal.titulo, amostra.sinal.pk)
    excluidas = [(c, len(e)) for c, e in classes.items() if len(e) < 2]
    classes = {c: e for c, e in classes.items() if len(e) >= 2}
    if not classes:
        raise ErroTemporal(
            "Toda classe tem menos de duas amostras — impossível calibrar o "
            "limiar de rejeição. Grave mais amostras por sinal (exemplos "
            "negativos não contam como classe)."
        )
    pares_negativos = [(a.pk, t) for a, t in negativos]
    calibracao = {
        classe: _calibrar(entradas, pares_negativos)
        for classe, entradas in classes.items()
    }
    modelo = {
        "formato": FORMATO_MODELO,
        "treinado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "classes": sorted(classes),
        "sinal_id": {c: sinal_ids[c] for c in classes},
        "templates": {
            c: [
                {"amostra_id": pk, "trajetoria": t} for pk, t in entradas
            ]
            for c, entradas in classes.items()
        },
        "amostras_por_classe": {c: len(e) for c, e in classes.items()},
        "loo": {
            c: [
                {"amostra": pk, "vizinho": viz, "distancia": d}
                for pk, viz, d in calibracao[c]["loo"]
            ]
            for c in classes
        },
        "limiares": {c: calibracao[c]["limiar"] for c in classes},
        "negativos": [
            {"amostra_id": a.pk, "sinal": a.sinal.titulo, "trajetoria": t}
            for a, t in negativos
        ],
        "calibracao": {
            c: {
                "negativo_min": calibracao[c]["negativo_min"],
                "sobreposicao": calibracao[c]["sobreposicao"],
            }
            for c in classes
        },
        "margem": MARGEM_LIMIAR,
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, destino, compress=COMPRESSAO_MODELOS)
    return TreinoResultado(
        modelo=modelo, trajetorias=trajetorias,
        invalidas=invalidas, excluidas=excluidas,
    )


def carregar_modelo(caminho=None):
    """Carrega o modelo salvo; falhas viram mensagens de terminal."""
    destino = _caminho(caminho)
    if not destino.exists():
        raise ErroTemporal(
            "Modelo de movimentos ausente. Execute primeiro: "
            "python manage.py treinar_movimentos"
        )
    try:
        modelo = joblib.load(destino)
    except (OSError, ValueError) as exc:
        raise ErroTemporal(f"Não foi possível carregar o modelo: {exc}")
    if not isinstance(modelo, dict) or modelo.get("formato") != FORMATO_MODELO:
        raise ErroTemporal(
            "Modelo em formato desconhecido — treine novamente com "
            "treinar_movimentos."
        )
    return modelo


def _sem(entradas, excluir_amostra):
    return [
        (e["amostra_id"], e["trajetoria"])
        for e in entradas
        if e["amostra_id"] != excluir_amostra
    ]


def _limiar_da_classe(modelo, classe, excluir_amostra=None):
    """Limiar da classe, recalculado sem a amostra excluída, se possível."""
    if excluir_amostra is None:
        return modelo["limiares"][classe]
    entradas = _sem(modelo["templates"][classe], excluir_amostra)
    if len(entradas) < 2:
        return modelo["limiares"][classe]
    negativos = _sem(modelo["negativos"], excluir_amostra)
    return _calibrar(entradas, negativos)["limiar"]


def prever(trajetoria, modelo, excluir_amostra=None):
    """Prevê a classe de uma trajetória (vizinho mais próximo por DTW).

    A trajetória precisa vir de ``processar_frames`` /
    ``processar_sequencia`` — os templates do modelo saem de lá.
    ``excluir_amostra`` ignora o template com esse id — é o que torna
    o teste leave-one-out honesto para uma amostra que participou do
    treino. O limiar da classe prevista é recalculado sem ela quando
    sobram templates suficientes.

    A entrada é rejeitada se passar do limiar da classe mais próxima
    ou se um exemplo negativo estiver ainda mais perto dela.
    """
    candidatos = []
    for classe, entradas in modelo["templates"].items():
        for entrada in entradas:
            if (
                excluir_amostra is not None
                and entrada["amostra_id"] == excluir_amostra
            ):
                continue
            candidatos.append((classe, entrada["amostra_id"], entrada["trajetoria"]))
    if not candidatos:
        raise ErroTemporal(
            "O modelo não tem templates para comparar. Treine novamente "
            "com treinar_movimentos."
        )
    distancias = [
        (distancia_dtw(trajetoria, t), classe, pk)
        for classe, pk, t in candidatos
    ]
    distancia, previsto, vizinho = min(distancias, key=lambda item: item[0])
    limiar = _limiar_da_classe(modelo, previsto, excluir_amostra)
    negativo = None
    for entrada in modelo["negativos"]:
        if entrada["amostra_id"] == excluir_amostra:
            continue
        d = distancia_dtw(trajetoria, entrada["trajetoria"])
        if negativo is None or d < negativo["distancia"]:
            negativo = {
                "sinal": entrada["sinal"],
                "amostra": entrada["amostra_id"],
                "distancia": d,
            }
    if distancia > limiar:
        motivo = "limiar"
    elif negativo is not None and negativo["distancia"] < distancia:
        motivo = "negativo"
    else:
        motivo = None
    confianca = max(0.0, 1.0 - distancia / limiar) if limiar > 0 else 0.0
    if motivo == "negativo":
        confianca = 0.0
    return {
        "previsto": previsto,
        "distancia": distancia,
        "limiar": limiar,
        "confianca": min(confianca, 1.0),
        "reconhecido": motivo is None,
        "motivo_rejeicao": motivo,
        "negativo_mais_proximo": negativo,
        "vizinho_amostra": vizinho,
        "classes": modelo["classes"],
    }


def testar_amostra(amostra_pk, caminho=None):
    """Pipeline completo de teste: valida, processa e prevê uma amostra.

    Quando a amostra participou do treino, ela é excluída dos
    templates (leave-one-out) para o resultado não sair inflado.
    """
    try:
        amostra = AmostraMovimento.objects.get(
            pk=amostra_pk,
            ativo=True,
            sinal__ativo=True,
            sinal__tipo=Sinal.Tipo.MOVIMENTO,
        )
    except AmostraMovimento.DoesNotExist:
        raise ErroTemporal(
            f"Amostra #{amostra_pk} não encontrada (precisa pertencer a um "
            "sinal de movimento ativo)."
        )
    trajetoria, resultado = carregar_sequencia(amostra)
    if trajetoria is None:
        detalhes = " · ".join(resultado.problemas)
        raise ErroTemporal(f"Amostra #{amostra_pk} é inválida: {detalhes}")
    modelo = carregar_modelo(caminho)
    no_treino = any(
        entrada["amostra_id"] == amostra.pk
        for entradas in [*modelo["templates"].values(), modelo["negativos"]]
        for entrada in entradas
    )
    previsao = prever(
        trajetoria, modelo,
        excluir_amostra=amostra.pk if no_treino else None,
    )
    previsao.update({
        "amostra": amostra,
        "esperado": amostra.sinal.titulo,
        "negativo": amostra.sinal.negativo,
        "frames_brutos": resultado.total_frames,
        "frames_processados": len(trajetoria),
        "modo_loo": no_treino,
        "total_amostras_modelo": sum(modelo["amostras_por_classe"].values()),
    })
    return previsao


def testar_arquivo(caminho, caminho_modelo=None):
    """Testa um JSON externo (formato de amostra) contra o modelo.

    Etapa 4.3 — entrada controlada de não-J: o arquivo nunca esteve
    nos templates, então nada é excluído e não há leave-one-out. A
    validação estrutural reaproveita a Etapa 4.1 (``verificar_conteudo``
    sem vínculo com o banco). O esperado é rejeição quando o movimento
    não casa com nenhuma classe — aceitar uma entrada não-J é falso
    positivo, e o comando relata exatamente isso.
    """
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroTemporal(f"Arquivo não encontrado: {caminho}")
    try:
        conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErroTemporal(f"JSON inválido: {exc}")
    resultado = verificar_conteudo(conteudo)
    if not resultado.ok:
        detalhes = " · ".join(resultado.problemas)
        raise ErroTemporal(f"Arquivo estruturalmente inválido: {detalhes}")
    trajetoria = processar_sequencia(conteudo)
    modelo = carregar_modelo(caminho_modelo)
    previsao = prever(trajetoria, modelo)
    previsao.update({
        "arquivo": str(caminho),
        "esperado": "não-J",
        "frames_brutos": resultado.total_frames,
        "frames_processados": len(trajetoria),
        "modo_loo": False,
        "total_amostras_modelo": sum(modelo["amostras_por_classe"].values()),
    })
    return previsao
