"""Pipeline temporal experimental (Etapa 4.2).

Primeiro protótipo de reconhecimento de movimentos a partir das
amostras gravadas pela coleta temporal (``libras.movimentos``):

1. validação estrutural reaproveitada da Etapa 4.1
   (``libras.verificacao.verificar_amostra``);
2. conversão dos frames em uma trajetória normalizada (landmarks
   relativos ao pulso e invariantes à escala; frames vazios das
   pontas são truncados, os do meio interpolados por timestamp);
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from .models import AmostraMovimento, Sinal
from .movimentos import LANDMARKS_POR_MAO, VALORES_POR_LANDMARK, ler_sequencia
from .verificacao import verificar_amostra, verificar_conteudo

MODELO_PATH = Path(__file__).resolve().parent.parent / "models" / "movimentos.joblib"
FORMATO_MODELO = 1
# Fator de segurança sobre a maior distância leave-one-out da classe.
MARGEM_LIMIAR = 2.0
# Piso do limiar: evita aceitar tudo quando amostras são idênticas.
LIMIAR_MINIMO = 0.05
VALORES_POR_FRAME = LANDMARKS_POR_MAO * VALORES_POR_LANDMARK


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


def processar_sequencia(conteudo):
    """JSON da amostra → trajetória normalizada (lista de 63-vetores).

    Frames sem landmarks recebem tratamento explícito: os das pontas
    são truncados (a mão ainda não entrou / já saiu do quadro) e os
    do meio são interpolados linearmente por timestamp entre os
    vizinhos válidos — o padrão temporal é preservado sem descartar
    frames do meio do movimento.
    """
    frames = conteudo["frames"]
    validos = {i for i, f in enumerate(frames) if f["landmarks"] is not None}
    if not validos:
        return []
    primeiro, ultimo = min(validos), max(validos)
    trajetoria = []
    for indice in range(primeiro, ultimo + 1):
        frame = frames[indice]
        if frame["landmarks"] is not None:
            trajetoria.append(normalizar_frame(frame["landmarks"]))
            continue
        anterior = max(v for v in validos if v < indice)
        proximo = min(v for v in validos if v > indice)
        fa, fb = frames[anterior], frames[proximo]
        ta, tb = fa["timestamp_ms"], fb["timestamp_ms"]
        peso = (
            (frame["timestamp_ms"] - ta) / (tb - ta) if tb > ta else 0.0
        )
        interpolado = [
            a + (b - a) * peso for a, b in zip(fa["landmarks"], fb["landmarks"])
        ]
        trajetoria.append(normalizar_frame(interpolado))
    return trajetoria


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


def _limiar_de(distancias):
    maxima = max(d for _, _, d in distancias) if distancias else 0.0
    return max(maxima * MARGEM_LIMIAR, LIMIAR_MINIMO)


def _caminho(caminho):
    return Path(caminho) if caminho is not None else MODELO_PATH


def treinar(caminho=None):
    """Treina o protótipo: memoriza trajetórias e calibra limiares.

    O limiar de cada classe é a maior distância leave-one-out
    intra-classe vezes ``MARGEM_LIMIAR`` — abaixo dele a previsão é
    "parecido o suficiente", acima é rejeitada. Classes com menos de
    duas amostras ficam de fora (não há como calibrar o limiar). Com
    uma única classe o modelo demonstra correspondência ao padrão,
    não discriminação entre sinais.
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
    for amostra, trajetoria in validas:
        classes.setdefault(amostra.sinal.titulo, []).append(
            (amostra.pk, trajetoria)
        )
        sinal_ids.setdefault(amostra.sinal.titulo, amostra.sinal.pk)
    excluidas = [(c, len(e)) for c, e in classes.items() if len(e) < 2]
    classes = {c: e for c, e in classes.items() if len(e) >= 2}
    if not classes:
        raise ErroTemporal(
            "Toda classe tem menos de duas amostras — impossível calibrar o "
            "limiar de rejeição. Grave mais amostras por sinal."
        )
    loo = {classe: _loo(entradas) for classe, entradas in classes.items()}
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
                for pk, viz, d in loo[c]
            ]
            for c in classes
        },
        "limiares": {c: _limiar_de(loo[c]) for c in classes},
        "margem": MARGEM_LIMIAR,
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, destino)
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


def _limiar_da_classe(modelo, classe, excluir_amostra=None):
    """Limiar da classe, recalculado sem a amostra excluída, se possível."""
    if excluir_amostra is None:
        return modelo["limiares"][classe]
    entradas = [
        (e["amostra_id"], e["trajetoria"])
        for e in modelo["templates"][classe]
        if e["amostra_id"] != excluir_amostra
    ]
    if len(entradas) < 2:
        return modelo["limiares"][classe]
    return _limiar_de(_loo(entradas))


def prever(trajetoria, modelo, excluir_amostra=None):
    """Prevê a classe de uma trajetória (vizinho mais próximo por DTW).

    A trajetória precisa estar normalizada (``processar_sequencia`` /
    ``normalizar_frame``) — os templates do modelo estão normalizados.
    ``excluir_amostra`` ignora o template com esse id — é o que torna
    o teste leave-one-out honesto para uma amostra que participou do
    treino. O limiar da classe prevista é recalculado sem ela quando
    sobram templates suficientes.
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
    confianca = max(0.0, 1.0 - distancia / limiar) if limiar > 0 else 0.0
    return {
        "previsto": previsto,
        "distancia": distancia,
        "limiar": limiar,
        "confianca": min(confianca, 1.0),
        "reconhecido": distancia <= limiar,
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
        for entradas in modelo["templates"].values()
        for entrada in entradas
    )
    previsao = prever(
        trajetoria, modelo,
        excluir_amostra=amostra.pk if no_treino else None,
    )
    previsao.update({
        "amostra": amostra,
        "esperado": amostra.sinal.titulo,
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
