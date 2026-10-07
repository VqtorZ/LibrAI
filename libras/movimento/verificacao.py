"""Verificador estrutural das amostras temporais (Etapa 4.1).

Diagnóstico da coleta: confere se os arquivos JSON escritos por
``libras.movimento.amostras`` estão íntegros, completos e coerentes com os
metadados do banco. Apenas lê e reporta — não treina, não classifica
e não reconhece sinais; o status final declara somente se os dados
estão estruturalmente prontos para uma futura etapa de treinamento.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..captura.marcos import MAOS_VALIDAS
from .amostras import (
    FRAMES_MIN_VALIDOS,
    LANDMARKS_POR_MAO,
    VALORES_POR_LANDMARK,
    VERSOES_SUPORTADAS,
    AmostraInvalida,
    ler_sequencia,
)

VALORES_POR_FRAME = LANDMARKS_POR_MAO * VALORES_POR_LANDMARK

# Campos escritos por salvar_amostra; todos devem estar presentes no JSON.
CHAVES_OBRIGATORIAS = (
    "version",
    "sinal_id",
    "quantidade_frames",
    "quantidade_frames_validos",
    "duracao_ms",
    "fps",
    "quantidade_landmarks",
    "frames",
)


@dataclass
class ResultadoVerificacao:
    """Diagnóstico de uma amostra temporal individual."""

    ok: bool = False
    arquivo_legivel: bool = False
    problemas: list[str] = field(default_factory=list)
    total_frames: int = 0
    frames_validos: int = 0
    frames_sem_landmarks: int = 0
    duracao_ms: int = 0
    fps: float = 0.0

    @property
    def taxa_validos(self) -> float:
        if not self.total_frames:
            return 0.0
        return self.frames_validos / self.total_frames * 100

    @property
    def duracao_segundos(self) -> float:
        return self.duracao_ms / 1000


@dataclass
class ResumoDataset:
    """Consolidação dos resultados das amostras de um sinal."""

    amostras: int = 0
    validas: int = 0
    invalidas: int = 0
    frames_totais: int = 0
    frames_validos: int = 0
    taxa_media: float = 0.0
    duracao_media_s: float = 0.0

    @property
    def pronto(self) -> bool:
        return self.amostras > 0 and self.invalidas == 0


def _numero(valor) -> bool:
    """Numérico, finito e não-booleano (bool é subclasse de int)."""
    return (
        not isinstance(valor, bool)
        and isinstance(valor, (int, float))
        and math.isfinite(valor)
    )


def _fps_de(duracao_ms: int, total_frames: int) -> float:
    """Mesma fórmula de amostras.salvar_amostra."""
    if duracao_ms <= 0:
        return 0.0
    return round((total_frames - 1) / (duracao_ms / 1000), 1)


def _conferir_campo(problemas, nome, valor_arquivo, valor_real):
    """Compara um metadado do JSON com o valor recalculado dos frames."""
    if not _numero(valor_arquivo):
        if valor_arquivo is not None:
            problemas.append(f"campo '{nome}' do arquivo não é numérico")
        return
    if valor_arquivo != valor_real:
        problemas.append(
            f"campo '{nome}' do arquivo ({valor_arquivo}) difere do real ({valor_real})"
        )


def _conferir_banco(problemas, nome, valor_modelo, valor_arquivo):
    """Compara um metadado do registro no banco com o do arquivo."""
    if not _numero(valor_arquivo):
        return  # a ausência/tipo do campo já foi criticada na leitura
    if valor_modelo != valor_arquivo:
        problemas.append(
            f"registro no banco ({nome}={valor_modelo}) difere do arquivo ({valor_arquivo})"
        )


def verificar_conteudo(conteudo, sinal_id_esperado=None) -> ResultadoVerificacao:
    """Valida estrutura e consistência interna de um JSON de amostra.

    É a parte de ``verificar_amostra`` que não depende do banco de
    dados — serve também para arquivos externos (Etapa 4.3, teste de
    rejeição com entradas não-J). ``sinal_id_esperado`` confere o
    vínculo com um sinal quando aplicável; ``None`` pula a checagem
    (o arquivo não pertence a nenhum sinal registrado).
    """
    resultado = ResultadoVerificacao(arquivo_legivel=True)
    problemas = resultado.problemas
    if not isinstance(conteudo, dict):
        problemas.append("conteúdo do arquivo não é um objeto")
        return resultado

    for chave in CHAVES_OBRIGATORIAS:
        if chave not in conteudo:
            problemas.append(f"estrutura incompleta: campo '{chave}' ausente")

    frames = conteudo.get("frames")
    if not isinstance(frames, list):
        frames = []
    elif not frames:
        problemas.append("nenhum frame no arquivo")
    resultado.total_frames = len(frames)

    timestamps = []
    frames_com_landmarks = 0
    timestamp_anterior = None
    for indice, frame in enumerate(frames):
        if (
            not isinstance(frame, dict)
            or "timestamp_ms" not in frame
            or "landmarks" not in frame
        ):
            problemas.append(f"frame {indice}: estrutura inválida")
            continue
        timestamp = frame["timestamp_ms"]
        if not _numero(timestamp):
            problemas.append(
                f"frame {indice}: timestamp inválido (não numérico ou não finito)"
            )
        else:
            if timestamp_anterior is not None and timestamp < timestamp_anterior:
                problemas.append(f"frame {indice}: timestamps fora de ordem")
            timestamp_anterior = timestamp
            timestamps.append(timestamp)
        if frame.get("mao") is not None and frame["mao"] not in MAOS_VALIDAS:
            problemas.append(f"frame {indice}: mão '{frame['mao']}' inválida")
        landmarks = frame["landmarks"]
        if landmarks is None:
            resultado.frames_sem_landmarks += 1
            continue
        frames_com_landmarks += 1
        if not isinstance(landmarks, list):
            problemas.append(f"frame {indice}: landmarks não são uma lista")
            continue
        if not all(_numero(valor) for valor in landmarks):
            problemas.append(
                f"frame {indice}: landmarks com valores não numéricos ou não finitos"
            )
            continue
        if len(landmarks) != VALORES_POR_FRAME:
            problemas.append(
                f"frame {indice} possui {len(landmarks)} valores em vez de {VALORES_POR_FRAME}"
            )
            continue
        resultado.frames_validos += 1

    if len(timestamps) >= 2:
        resultado.duracao_ms = int(max(timestamps[-1] - timestamps[0], 0))
    resultado.fps = _fps_de(resultado.duracao_ms, resultado.total_frames)

    if resultado.frames_validos < FRAMES_MIN_VALIDOS:
        problemas.append(
            f"apenas {resultado.frames_validos} frames válidos (mínimo {FRAMES_MIN_VALIDOS})"
        )

    if "version" in conteudo and conteudo["version"] not in VERSOES_SUPORTADAS:
        suportadas = ", ".join(str(v) for v in VERSOES_SUPORTADAS)
        problemas.append(
            f"versão do arquivo ({conteudo['version']}) inesperada (suportadas: {suportadas})"
        )
    if sinal_id_esperado is not None and "sinal_id" in conteudo:
        if conteudo["sinal_id"] != sinal_id_esperado:
            problemas.append(
                f"sinal_id do arquivo ({conteudo['sinal_id']}) não corresponde "
                f"à amostra ({sinal_id_esperado})"
            )

    _conferir_campo(
        problemas, "quantidade_frames",
        conteudo.get("quantidade_frames"), resultado.total_frames,
    )
    _conferir_campo(
        problemas, "quantidade_frames_validos",
        conteudo.get("quantidade_frames_validos"), frames_com_landmarks,
    )
    _conferir_campo(
        problemas, "quantidade_landmarks",
        conteudo.get("quantidade_landmarks"), LANDMARKS_POR_MAO,
    )
    _conferir_campo(
        problemas, "duracao_ms",
        conteudo.get("duracao_ms"), resultado.duracao_ms,
    )
    fps_arquivo = conteudo.get("fps")
    if _numero(fps_arquivo):
        if abs(fps_arquivo - resultado.fps) > 0.05:
            problemas.append(
                f"campo 'fps' do arquivo ({fps_arquivo}) difere do real ({resultado.fps})"
            )
    elif fps_arquivo is not None:
        problemas.append("campo 'fps' do arquivo não é numérico")

    resultado.ok = not problemas
    return resultado


def verificar_amostra(amostra) -> ResultadoVerificacao:
    """Verifica a estrutura de uma AmostraMovimento e do seu arquivo JSON.

    A leitura reaproveita ``ler_sequencia`` de ``amostras`` —
    nada da persistência é duplicado aqui. Frames com ``landmarks:
    null`` são permitidos pelo formato e não invalidam a amostra.
    """
    resultado = ResultadoVerificacao()

    try:
        conteudo = ler_sequencia(amostra)
    except AmostraInvalida as exc:
        resultado.problemas.append(f"arquivo não pode ser lido: {str(exc).rstrip('.')}")
        return resultado

    resultado = verificar_conteudo(conteudo, sinal_id_esperado=amostra.sinal_id)
    problemas = resultado.problemas

    _conferir_banco(
        problemas, "quantidade_frames",
        amostra.quantidade_frames, conteudo.get("quantidade_frames"),
    )
    _conferir_banco(
        problemas, "duracao_ms",
        amostra.duracao_ms, conteudo.get("duracao_ms"),
    )
    _conferir_banco(
        problemas, "quantidade_landmarks",
        amostra.quantidade_landmarks, conteudo.get("quantidade_landmarks"),
    )
    _conferir_banco(
        problemas, "versao_features",
        amostra.versao_features, conteudo.get("version"),
    )
    if _numero(conteudo.get("fps")) and abs(amostra.fps - conteudo["fps"]) > 0.05:
        problemas.append(
            f"registro no banco (fps={amostra.fps}) difere do arquivo ({conteudo['fps']})"
        )

    resultado.ok = not problemas
    return resultado


def resumir(resultados) -> ResumoDataset:
    """Consolida os resultados por sinal em métricas do dataset.

    Amostras ilegíveis não têm métricas e ficam fora das somas e
    médias — o restante do quadro (válido/inválido) continua contando.
    """
    legiveis = [r for r in resultados if r.arquivo_legivel]
    taxas = [r.taxa_validos for r in legiveis if r.total_frames]
    duracoes = [r.duracao_segundos for r in legiveis]
    validas = sum(1 for r in resultados if r.ok)
    return ResumoDataset(
        amostras=len(resultados),
        validas=validas,
        invalidas=len(resultados) - validas,
        frames_totais=sum(r.total_frames for r in legiveis),
        frames_validos=sum(r.frames_validos for r in legiveis),
        taxa_media=sum(taxas) / len(taxas) if taxas else 0.0,
        duracao_media_s=sum(duracoes) / len(duracoes) if duracoes else 0.0,
    )
