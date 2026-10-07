"""Gravação de amostras: comando gravar_movimento e página do sinal."""
import time
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from libras.models import AmostraMovimento, Sinal
from libras.movimento.amostras import (
    DURACAO_MAX_MS,
    AmostraInvalida,
    ler_sequencia,
    salvar_amostra,
)
from libras.movimento.gravacao import GravadorMovimento, localizar_sinal
from libras.movimento.verificacao import verificar_amostra

from .base import TemporalBase


class GravarMovimentoTests(TemporalBase):
    """Gravação pelo OpenCV: localização do sinal e montagem da amostra."""

    def test_localiza_por_titulo_sem_diferenciar_caixa(self):
        self.assertEqual(localizar_sinal("j"), self.sinal)

    def test_localiza_por_numero(self):
        self.assertEqual(localizar_sinal(str(self.sinal.pk)), self.sinal)

    def test_sinal_inexistente_lista_os_disponiveis(self):
        with self.assertRaises(AmostraInvalida) as contexto:
            localizar_sinal("Z")
        self.assertIn("J (#", str(contexto.exception))
        self.assertIn("/gestos/novo/", str(contexto.exception))

    def test_sinal_estatico_nao_e_aceito(self):
        Sinal.objects.create(titulo="A")
        with self.assertRaises(AmostraInvalida):
            localizar_sinal("A")

    def test_titulo_ambiguo_pede_o_numero(self):
        Sinal.objects.create(titulo="J", tipo=Sinal.Tipo.MOVIMENTO)
        with self.assertRaises(AmostraInvalida) as contexto:
            localizar_sinal("J")
        self.assertIn("Use o número", str(contexto.exception))

    def test_grava_e_salva_com_origem_opencv(self):
        gravador = GravadorMovimento(self.sinal)
        self.assertFalse(gravador.gravando)
        gravador.iniciar(100.0)
        for i in range(30):
            self.assertTrue(gravador.adicionar(100.0 + i / 30, [0.5] * 63, "Right"))
        amostra = gravador.finalizar()
        self.assertFalse(gravador.gravando)
        self.assertEqual(amostra.quantidade_frames, 30)
        conteudo = ler_sequencia(amostra)
        self.assertEqual(conteudo["origem"], "opencv")
        self.assertEqual(conteudo["frames"][0]["mao"], "Right")
        self.assertEqual(conteudo["frames"][1]["timestamp_ms"], 33)
        self.assertTrue(verificar_amostra(amostra).ok)

    def test_para_no_limite_de_duracao(self):
        gravador = GravadorMovimento(self.sinal)
        gravador.iniciar(0.0)
        self.assertTrue(gravador.adicionar(1.0, [0.5] * 63, None))
        self.assertFalse(gravador.adicionar(DURACAO_MAX_MS / 1000 + 0.1, [0.5] * 63, None))

    def test_gravacao_curta_e_rejeitada(self):
        gravador = GravadorMovimento(self.sinal)
        gravador.iniciar(0.0)
        gravador.adicionar(0.0, None, None)
        with self.assertRaises(AmostraInvalida):
            gravador.finalizar()
        self.assertEqual(AmostraMovimento.objects.count(), 0)
        with self.assertRaises(AmostraInvalida):
            gravador.finalizar()  # sem frames

    def test_descartar(self):
        gravador = GravadorMovimento(self.sinal)
        gravador.iniciar(0.0)
        gravador.adicionar(0.1, [0.5] * 63, None)
        gravador.descartar()
        self.assertFalse(gravador.gravando)
        self.assertFalse(gravador.adicionar(0.2, [0.5] * 63, None))

    def test_comando_com_sinal_inexistente(self):
        with self.assertRaises(CommandError) as contexto:
            call_command("gravar_movimento", "Z", stdout=StringIO())
        self.assertIn("não encontrado", str(contexto.exception))

    def test_origem_padrao_e_opencv(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        self.assertEqual(ler_sequencia(amostra)["origem"], "opencv")


class GravacaoPelaPaginaTests(TemporalBase):
    """Gravação pela página do sinal, usando a câmera do reconhecimento.

    A webcam não é aberta: o estado da câmera é simulado (frame recente,
    mão presente) e os frames entram por ``_registrar_gravacao``, o
    mesmo caminho usado por ``_annotate``.
    """

    def setUp(self):
        super().setUp()
        from libras.captura import camera as modulo_camera

        self.camera = modulo_camera.camera
        self.addCleanup(self.camera.descartar_gravacao)
        self.camera_pronta()

    def camera_pronta(self, mao=True):
        self.camera._ultimo_frame = time.monotonic()
        self.camera._mao_presente = mao

    def post(self, nome, sinal=None):
        return self.client.post(reverse(nome, args=[(sinal or self.sinal).pk]))

    def gravar_frames(self, total=30):
        inicio = time.monotonic()
        with self.camera._lock:
            for i in range(total):
                self.camera._registrar_gravacao([0.5] * 63, "Right", inicio + i / 30)

    def test_grava_e_salva_pela_pagina(self):
        self.assertEqual(self.post("gesto_gravacao_iniciar").json(), {"ok": True})
        status = self.client.get(reverse("status")).json()["recording"]
        self.assertTrue(status["ativa"])
        self.assertEqual(status["sinal_id"], self.sinal.pk)
        self.gravar_frames()
        resposta = self.post("gesto_gravacao_parar")
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertTrue(dados["ok"])
        amostra = AmostraMovimento.objects.get(pk=dados["amostra_id"])
        self.assertEqual(amostra.sinal, self.sinal)
        self.assertEqual(ler_sequencia(amostra)["origem"], "opencv")
        self.assertTrue(verificar_amostra(amostra).ok)
        self.assertFalse(self.client.get(reverse("status")).json()["recording"]["ativa"])

    def test_nao_inicia_sem_mao(self):
        self.camera_pronta(mao=False)
        resposta = self.post("gesto_gravacao_iniciar")
        self.assertEqual(resposta.status_code, 409)
        self.assertIn("Posicione a mão", resposta.json()["erro"])

    def test_nao_inicia_sem_camera_transmitindo(self):
        self.camera._ultimo_frame = 0.0
        resposta = self.post("gesto_gravacao_iniciar")
        self.assertEqual(resposta.status_code, 409)
        self.assertIn("não está transmitindo", resposta.json()["erro"])

    def test_uma_gravacao_por_vez(self):
        self.post("gesto_gravacao_iniciar")
        outro = Sinal.objects.create(titulo="Z", tipo=Sinal.Tipo.MOVIMENTO)
        resposta = self.post("gesto_gravacao_iniciar", outro)
        self.assertEqual(resposta.status_code, 409)
        # Parar pelo outro sinal também não mexe na gravação do J.
        self.assertEqual(self.post("gesto_gravacao_parar", outro).status_code, 409)
        self.assertTrue(self.camera.status_gravacao()["ativa"])

    def test_gravacao_sem_mao_suficiente_e_descartada(self):
        self.post("gesto_gravacao_iniciar")
        resposta = self.post("gesto_gravacao_parar")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Amostra descartada", resposta.json()["erro"])
        self.assertEqual(AmostraMovimento.objects.count(), 0)
        self.assertFalse(self.camera.status_gravacao()["ativa"])

    def test_parar_sem_gravacao(self):
        self.assertEqual(self.post("gesto_gravacao_parar").status_code, 409)

    def test_limite_de_duracao_sinaliza_a_pagina(self):
        self.post("gesto_gravacao_iniciar")
        inicio = time.monotonic()
        with self.camera._lock:
            self.camera._registrar_gravacao([0.5] * 63, None, inicio + DURACAO_MAX_MS / 1000 + 1)
        self.assertTrue(self.camera.status_gravacao()["no_limite"])

    def test_rotas_exigem_post_e_sinal_de_movimento(self):
        url = reverse("gesto_gravacao_iniciar", args=[self.sinal.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        estatico = Sinal.objects.create(titulo="A")
        self.assertEqual(self.post("gesto_gravacao_iniciar", estatico).status_code, 404)
        self.assertFalse(self.camera.status_gravacao()["ativa"])

    def test_status_informa_mao_e_gravacao(self):
        payload = self.client.get(reverse("status")).json()
        self.assertIn("hand_detected", payload)
        self.assertEqual(payload["recording"], {"ativa": False})
