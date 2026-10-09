"""Modo teste: página, validação dos resultados e histórico."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from libras import testes_ao_vivo
from libras.models import Sinal

from .base import entrar_como_admin


class ModoTesteTests(TestCase):
    def setUp(self):
        entrar_como_admin(self)
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        self.arquivo = pasta / "testes.jsonl"
        ajuste = patch("libras.caminhos.TESTES_AO_VIVO", self.arquivo)
        ajuste.start()
        self.addCleanup(ajuste.stop)
        Sinal.objects.create(titulo="J", tipo=Sinal.Tipo.MOVIMENTO)
        Sinal.objects.create(titulo="J incompleto", tipo=Sinal.Tipo.MOVIMENTO, negativo=True)

    def salvar(self, corpo, **extra):
        return self.client.post(
            reverse("teste_ao_vivo_salvar"), json.dumps(corpo), content_type="application/json", **extra
        )

    def resultado(self, **mudar):
        corpo = {"letra": "M", "tentativas": 10, "acertos": 8, "tempos_ms": [500] * 8, "erros": {"N": 2}}
        corpo.update(mudar)
        return corpo

    def test_pagina_lista_letras_paradas_e_movimentos(self):
        resposta = self.client.get(reverse("teste_ao_vivo"))
        self.assertEqual(len(resposta.context["paradas"]), 21)
        self.assertEqual([m["letra"] for m in resposta.context["movimentos"]], ["J"])  # negativo fica de fora
        self.assertContains(resposta, 'id="video"')
        self.assertContains(resposta, "Nenhum teste ainda")
        self.assertContains(self.client.get(reverse("gestos")), reverse("teste_ao_vivo"))

    def test_salva_e_mostra_no_historico_com_variacao(self):
        self.assertEqual(self.salvar(self.resultado()).json(), {"ok": True})
        self.salvar(self.resultado(acertos=10, tempos_ms=[400] * 10, erros={}))
        registros = [json.loads(l) for l in self.arquivo.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(registros), 2)
        self.assertEqual(registros[0]["tipo"], "parada")
        self.assertEqual(registros[0]["por_onde"], "pelo link")
        self.assertIn("quando", registros[0])
        historico = testes_ao_vivo.historico()
        self.assertEqual(historico[0]["percentual"], 100)
        self.assertEqual(historico[0]["variacao"], 20)  # 80% → 100%
        self.assertEqual(historico[0]["tempo_medio_ms"], 400)
        self.assertIsNone(historico[1]["variacao"])
        pagina = self.client.get(reverse("teste_ao_vivo"))
        self.assertContains(pagina, "10/10 (100%)")
        self.assertContains(pagina, "▲ +20")
        self.assertContains(pagina, "N (2)")

    def test_no_proprio_pc_fica_separado_do_link(self):
        self.salvar(self.resultado(), HTTP_HOST="localhost:8080")
        self.salvar(self.resultado(acertos=5, tempos_ms=[900] * 5, erros={"N": 5}))
        historico = testes_ao_vivo.historico()
        self.assertEqual({h["por_onde"] for h in historico}, {"no PC", "pelo link"})
        # Caminhos diferentes não se comparam entre si.
        self.assertTrue(all(h["variacao"] is None for h in historico))

    def test_movimento_aceito(self):
        self.assertEqual(self.salvar(self.resultado(letra="J", erros={"não reconheceu": 2})).status_code, 200)
        self.assertEqual(testes_ao_vivo.historico()[0]["tipo"], "movimento")

    def test_resultados_invalidos(self):
        casos = [
            self.resultado(letra="Ç"),
            self.resultado(letra="J incompleto"),
            self.resultado(acertos=11),
            self.resultado(tentativas=0),
            self.resultado(tentativas=51, acertos=0, tempos_ms=[]),
            self.resultado(tempos_ms=[500] * 7),
            self.resultado(tempos_ms=[500] * 7 + [99999]),
            self.resultado(erros={"N": 3}),
            self.resultado(erros=["N"]),
            self.resultado(acertos=True),
            "não é json",
        ]
        for corpo in casos:
            with self.subTest(corpo=str(corpo)[:60]):
                resposta = (
                    self.client.post(reverse("teste_ao_vivo_salvar"), corpo, content_type="application/json")
                    if isinstance(corpo, str) else self.salvar(corpo)
                )
                self.assertEqual(resposta.status_code, 400)
        self.assertFalse(self.arquivo.exists())

    def test_so_admin_e_so_post(self):
        self.assertEqual(self.client.get(reverse("teste_ao_vivo_salvar")).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("teste_ao_vivo")).status_code, 302)
        self.assertEqual(self.salvar(self.resultado()).status_code, 302)
        self.assertFalse(self.arquivo.exists())
