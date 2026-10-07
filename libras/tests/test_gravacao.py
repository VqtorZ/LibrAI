"""Gravação de amostras de movimento pelo navegador (página do sinal)."""
import json

from django.urls import reverse

from libras.models import AmostraMovimento, Sinal
from libras.movimento.amostras import (
    DURACAO_MAX_MS,
    FORMATO_VERSAO,
    ler_sequencia,
    salvar_amostra,
)
from libras.movimento.verificacao import verificar_amostra

from .base import TemporalBase


def quadros(total=30, inicio=5000, passo=33, mao="Right", sem_mao=0):
    """Quadros como o navegador manda: {"t", "marcos", "mao"}."""
    return [
        {
            "t": inicio + i * passo,
            "marcos": None if i < sem_mao else [0.5 + 0.001 * i] * 63,
            "mao": None if i < sem_mao else mao,
        }
        for i in range(total)
    ]


class GravacaoPeloNavegadorTests(TemporalBase):
    """O navegador grava os quadros e manda tudo de uma vez ao parar."""

    def gravar(self, corpo, sinal=None):
        url = reverse("gesto_amostra_gravar", args=[(sinal or self.sinal).pk])
        dados = corpo if isinstance(corpo, str) else json.dumps(corpo)
        return self.client.post(url, dados, content_type="application/json")

    def test_grava_e_salva(self):
        resposta = self.gravar({"quadros": quadros()})
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertTrue(dados["ok"])
        self.assertEqual(dados["quantidade_frames"], 30)
        amostra = AmostraMovimento.objects.get(pk=dados["amostra_id"])
        self.assertEqual(amostra.sinal, self.sinal)
        self.assertEqual(amostra.versao_features, FORMATO_VERSAO)
        conteudo = ler_sequencia(amostra)
        self.assertEqual(conteudo["origem"], "navegador")
        self.assertEqual(conteudo["version"], FORMATO_VERSAO)
        # O tempo começa em zero, não no relógio do navegador.
        self.assertEqual(conteudo["frames"][0]["timestamp_ms"], 0)
        self.assertEqual(conteudo["frames"][1]["timestamp_ms"], 33)
        self.assertEqual(conteudo["frames"][0]["mao"], "Right")
        self.assertTrue(verificar_amostra(amostra).ok)

    def test_quadros_sem_mao_ficam_sem_lado(self):
        resposta = self.gravar({"quadros": quadros(sem_mao=5)})
        amostra = AmostraMovimento.objects.get(pk=resposta.json()["amostra_id"])
        conteudo = ler_sequencia(amostra)
        frames = conteudo["frames"]
        self.assertIsNone(frames[0]["landmarks"])
        self.assertIsNone(frames[0]["mao"])
        self.assertEqual(conteudo["quantidade_frames_validos"], 25)

    def test_dados_invalidos_sao_recusados(self):
        ruins = quadros()
        fora_de_ordem = quadros()
        fora_de_ordem[3]["t"] = 0
        pontos_a_menos = quadros()
        pontos_a_menos[0]["marcos"] = [0.5] * 62
        texto_no_lugar = quadros()
        texto_no_lugar[0]["marcos"] = ["0.5"] * 63
        exagerado = quadros()
        exagerado[0]["marcos"] = [1e6] * 63
        mao_estranha = quadros()
        mao_estranha[0]["mao"] = "Meio"
        casos = [
            "isto não é json",
            json.dumps([1, 2, 3]),
            {"quadros": []},
            {"quadros": "muitos"},
            {"quadros": fora_de_ordem},
            {"quadros": pontos_a_menos},
            {"quadros": texto_no_lugar},
            {"quadros": exagerado},
            {"quadros": mao_estranha},
            {"quadros": [{"marcos": None}] + ruins},
        ]
        for corpo in casos:
            with self.subTest(corpo=str(corpo)[:60]):
                resposta = self.gravar(corpo)
                self.assertEqual(resposta.status_code, 400)
                self.assertIn("Amostra descartada", resposta.json()["erro"])
        self.assertEqual(AmostraMovimento.objects.count(), 0)

    def test_limites_de_duracao_e_de_quadros(self):
        longa = quadros(total=2, passo=DURACAO_MAX_MS + 1)
        self.assertEqual(self.gravar({"quadros": longa}).status_code, 400)
        demais = quadros(total=1201, passo=1)
        self.assertEqual(self.gravar({"quadros": demais}).status_code, 400)
        self.assertEqual(AmostraMovimento.objects.count(), 0)

    def test_gravacao_sem_mao_suficiente_e_descartada(self):
        resposta = self.gravar({"quadros": quadros(total=12, sem_mao=5)})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Amostra descartada", resposta.json()["erro"])
        self.assertEqual(AmostraMovimento.objects.count(), 0)

    def test_rota_exige_post_e_sinal_de_movimento(self):
        url = reverse("gesto_amostra_gravar", args=[self.sinal.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        estatico = Sinal.objects.create(titulo="A")
        self.assertEqual(self.gravar({"quadros": quadros()}, estatico).status_code, 404)
        self.assertEqual(AmostraMovimento.objects.count(), 0)

    def test_pagina_de_gravacao_usa_a_camera_do_navegador(self):
        resposta = self.client.get(reverse("gesto_gravar", args=[self.sinal.pk]))
        self.assertContains(resposta, 'id="video"')
        self.assertContains(resposta, "js/camera-maos.js")
        self.assertContains(resposta, "modelos/hand_landmarker.task")
        self.assertContains(resposta, reverse("gesto_amostra_gravar", args=[self.sinal.pk]))

    def test_origem_padrao_e_navegador(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        self.assertEqual(ler_sequencia(amostra)["origem"], "navegador")
        self.assertEqual(amostra.versao_features, FORMATO_VERSAO)
