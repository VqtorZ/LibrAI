"""Bases e auxiliares compartilhados pelos testes."""
import json
import math
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings

from libras.models import Sinal
from libras.movimento import classificador
from libras.movimento.amostras import (
    salvar_amostra,
)
from libras.movimento.ao_vivo import DetectorMovimento


def entrar_como_admin(teste):
    """Faz o cliente de teste entrar como administrador (área de Gestos)."""
    # Sem senha: force_login não precisa dela, e criptografar uma senha
    # (lento de propósito) em cada teste deixava a suíte 10x mais lenta.
    usuario, _ = User.objects.get_or_create(
        username="admin@teste.com", defaults={"email": "admin@teste.com", "is_staff": True}
    )
    teste.client.force_login(usuario)
    return usuario


class TemporalBase(TestCase):
    """Isolamento do MEDIA_ROOT para os testes da coleta temporal."""

    @classmethod
    def setUpTestData(cls):
        cls.sinal = Sinal.objects.create(
            titulo="J", tipo=Sinal.Tipo.MOVIMENTO, descricao="Letra J"
        )

    def setUp(self):
        entrar_como_admin(self)
        self.media_tmp = tempfile.mkdtemp()
        ajuste = override_settings(MEDIA_ROOT=self.media_tmp)
        ajuste.enable()
        self.addCleanup(ajuste.disable)
        self.addCleanup(shutil.rmtree, self.media_tmp, ignore_errors=True)

    @staticmethod
    def gerar_sequencia(total=15, nulos=0, intervalo_ms=66):
        """Sequência sintética: 63 valores por frame, com 'nulos' frames sem mão."""
        sequencia = []
        for i in range(total):
            valido = i >= nulos
            sequencia.append({
                "timestamp_ms": i * intervalo_ms,
                "landmarks": [float(i % 10)] * 63 if valido else None,
            })
        return sequencia


class VerificadorBase(TemporalBase):
    """Base do verificador: helpers para inspecionar os JSONs de teste."""

    def ler_arquivo(self, amostra):
        caminho = Path(self.media_tmp) / amostra.arquivo_dados
        return json.loads(caminho.read_text(encoding="utf-8"))

    def escrever_arquivo(self, amostra, conteudo):
        caminho = Path(self.media_tmp) / amostra.arquivo_dados
        caminho.write_text(json.dumps(conteudo), encoding="utf-8")

    def rodar_comando(self):
        saida = StringIO()
        call_command("verificar_movimentos", stdout=saida, no_color=True)
        return saida.getvalue()


class TemporalMLBase(VerificadorBase):
    """Base do pipeline temporal: modelo isolado no MEDIA_ROOT de teste."""

    def setUp(self):
        super().setUp()
        ajuste = patch(
            "libras.movimento.classificador.MODELO_PATH",
            Path(self.media_tmp) / "movimentos_teste.joblib",
        )
        ajuste.start()
        self.addCleanup(ajuste.stop)

    @staticmethod
    def trajetoria_sintetica(total=20, fase=0.0):
        """Trajetória suave de 63 valores por frame, variando no tempo."""
        return [
            [math.sin(i / 3 + fase + j / 10) for j in range(63)]
            for i in range(total)
        ]

    def salvar_trajetoria(self, sinal, vetores, intervalo_ms=66):
        sequencia = [
            {"timestamp_ms": i * intervalo_ms, "landmarks": list(vetor)}
            for i, vetor in enumerate(vetores)
        ]
        return salvar_amostra(sinal, sequencia)

    def treinar_padrao(self, sinal, total=5, passo_fase=0.05):
        """Cria `total` amostras da mesma forma e treina o modelo."""
        pks = []
        for indice in range(total):
            amostra = self.salvar_trajetoria(
                sinal, self.trajetoria_sintetica(fase=indice * passo_fase)
            )
            pks.append(amostra.pk)
        return classificador.treinar(), pks

    @staticmethod
    def trajetoria_nao_j(total=36):
        """Sequência deliberadamente diferente de J (Etapa 4.3).

        DADO SINTÉTICO DE TESTE: mão fechada abrindo em leque com
        leve rotação e punho parado — muda a forma relativa da mão.
        """
        frames = []
        for indice in range(total):
            t = indice / (total - 1)
            pontos = [[0.0, 0.0, 0.0]]  # pulso na origem
            for k in range(1, 21):
                angulo = (k % 5) * (2 * math.pi / 5) + (k // 5) * 0.3 + 0.7 * t
                raio = 0.12 + 0.78 * t  # fechada → aberta
                pontos.append(
                    [raio * math.cos(angulo), raio * math.sin(angulo), 0.0]
                )
            frames.append([valor for ponto in pontos for valor in ponto])
        return frames

    @staticmethod
    def conteudo_json(vetores, sinal_id=None, intervalo_ms=66):
        """Conteúdo JSON no formato das amostras (Etapa 4.1)."""
        total = len(vetores)
        duracao = (total - 1) * intervalo_ms
        return {
            "version": 1,
            "sinal_id": sinal_id,
            "quantidade_frames": total,
            "quantidade_frames_validos": total,
            "duracao_ms": duracao,
            "fps": round((total - 1) / (duracao / 1000), 1) if duracao else 0.0,
            "quantidade_landmarks": 21,
            "frames": [
                {"timestamp_ms": i * intervalo_ms, "landmarks": list(vetor)}
                for i, vetor in enumerate(vetores)
            ],
        }

    def escrever_externo(self, vetores, sinal_id=None):
        """Grava um JSON externo de teste no MEDIA_ROOT temporário."""
        caminho = Path(self.media_tmp) / "externo.json"
        caminho.write_text(
            json.dumps(self.conteudo_json(vetores, sinal_id=sinal_id)),
            encoding="utf-8",
        )
        return caminho


def mao_sintetica(t, dx=0.0, dy=0.0, giro=0.0, tamanho=0.15):
    """63 valores crus de uma mão plausível em coordenadas de imagem.

    O pulso fica em (0.5 + dx, 0.5 + dy); os demais pontos giram em
    torno dele conforme ``t`` e ``giro`` — muda a forma relativa.
    """
    pulso = (0.5 + dx, 0.5 + dy)
    valores = [pulso[0], pulso[1], 0.0]
    for k in range(1, 21):
        angulo = (k % 5) * 0.5 + (k // 5) * 0.2 + giro * t - 1.0
        raio = tamanho * (0.4 + 0.15 * (k // 5 + 1))
        valores.extend((
            pulso[0] + raio * math.cos(angulo),
            pulso[1] - raio * math.sin(angulo),
            0.01 * k * tamanho,
        ))
    return valores


def frames_de(vetores, intervalo_ms=66, mao=None):
    """Lista de vetores crus → frames no formato das amostras."""
    return [
        {"timestamp_ms": i * intervalo_ms, "landmarks": list(v), "mao": mao}
        for i, v in enumerate(vetores)
    ]


class AoVivoBase(TemporalMLBase):
    """Auxiliares dos testes do detector ao vivo (câmera simulada)."""

    PASSO_MS = 33  # câmera ao vivo ~30 fps

    @staticmethod
    def gesto(total, variacao=0.0):
        return [
            mao_sintetica(
                i / (total - 1),
                dx=(0.3 + variacao) * i / (total - 1),
                giro=3.0 + variacao,
            )
            for i in range(total)
        ]

    def treinar_gesto(self):
        for indice in range(5):
            frames = frames_de(self.gesto(20, variacao=indice * 0.02))
            for frame in frames:
                frame["mao"] = None
            salvar_amostra(self.sinal, frames)
        return classificador.treinar()

    def alimentar(self, detector, vetores, inicio_ms=0):
        """Envia os frames ao detector; devolve [(ms, previsão)]."""
        saidas = []
        for indice, vetor in enumerate(vetores):
            ms = inicio_ms + indice * self.PASSO_MS
            previsao = detector.observar(ms, vetor, "Right" if vetor else None)
            if previsao is not None:
                saidas.append((ms, previsao))
        return saidas

    def detector(self):
        return DetectorMovimento(Path(self.media_tmp) / "movimentos_teste.joblib")
