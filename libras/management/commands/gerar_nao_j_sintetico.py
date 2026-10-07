"""Gera um JSON sintético de movimento NÃO-J para o teste de rejeição.

DADO SINTÉTICO DE TESTE — não é uma gravação real de Libras.

O movimento gerado é deliberadamente diferente da letra J: uma mão
fechada que se abre em leque com uma leve rotação, mudando a forma
relativa da mão em todos os frames, com o punho parado.

O arquivo sai no mesmo formato versionado das amostras reais
(etapa 4.1), pronto para:

    python manage.py gerar_nao_j_sintetico
    python manage.py testar_movimento --arquivo dados/sinteticos/nao_j_sintetico.json

O conteúdo carrega a marcação explícita "origem": "sintetico".
"""
import json
import math
from pathlib import Path

from django.core.management.base import BaseCommand

from .. import saida_segura
from ...caminhos import SINTETICOS

SAIDA = SINTETICOS / "nao_j_sintetico.json"
FRAMES = 36
INTERVALO_MS = 66
LANDMARKS = 21

DESCRICAO = (
    "DADO SINTÉTICO DE TESTE — não é uma gravação real. "
    "Movimento de mão fechada abrindo em leque com leve rotação, "
    "deliberadamente diferente da letra J (punho parado, dedo "
    "indicador traçando o gancho). Serve de entrada controlada "
    "para o teste de rejeição do modelo temporal."
)


def frame(indice):
    """Landmarks crus de um frame: pulso na origem, mão em leque."""
    t = indice / (FRAMES - 1)
    pontos = [[0.0, 0.0, 0.0]]  # landmark 0: pulso
    for k in range(1, LANDMARKS):
        angulo = (k % 5) * (2 * math.pi / 5) + (k // 5) * 0.3 + 0.7 * t
        raio = 0.12 + 0.78 * t  # mão fechada → mão aberta
        pontos.append([
            raio * math.cos(angulo),
            raio * math.sin(angulo),
            0.08 * math.sin(math.pi * t + k / 4),
        ])
    return [valor for ponto in pontos for valor in ponto]


def conteudo():
    """JSON no formato versionado das amostras, marcado como sintético."""
    duracao_ms = (FRAMES - 1) * INTERVALO_MS
    return {
        "version": 1,
        "sinal_id": None,
        "quantidade_frames": FRAMES,
        "quantidade_frames_validos": FRAMES,
        "duracao_ms": duracao_ms,
        "fps": round((FRAMES - 1) / (duracao_ms / 1000), 1),
        "quantidade_landmarks": LANDMARKS,
        "origem": "sintetico",
        "descricao": DESCRICAO,
        "frames": [
            {"timestamp_ms": i * INTERVALO_MS, "landmarks": frame(i)}
            for i in range(FRAMES)
        ],
    }


class Command(BaseCommand):
    help = "Gera o JSON sintético de movimento não-J para o teste de rejeição."

    def add_arguments(self, parser):
        parser.add_argument("--saida", default=str(SAIDA), help="Arquivo de saída.")

    def handle(self, *args, **options):
        saida_segura()
        saida = Path(options["saida"])
        saida.parent.mkdir(parents=True, exist_ok=True)
        saida.write_text(json.dumps(conteudo(), indent=1), encoding="utf-8")
        self.stdout.write(f"Arquivo sintético não-J criado em {saida}")
        self.stdout.write(
            f"Frames: {FRAMES} · duração: {(FRAMES - 1) * INTERVALO_MS} ms · origem: sintetico"
        )
