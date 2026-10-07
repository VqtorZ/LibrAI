"""Gravação do alfabeto pelo site: amostras, câmera, páginas e treino.

Nenhum teste toca no CSV real: o arquivo de amostras é redirecionado
para uma pasta temporária (``libras.estatico.amostras.AMOSTRAS_ESTATICAS``).
"""
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import joblib
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from libras.caminhos import salvar_modelo_atomico
from libras.captura import camera as modulo_camera
from libras.captura.camera import GravacaoIndisponivel
from libras.estatico import amostras
from libras.estatico.features import extrair_features, extrair_features_de_valores

MAO = [0.5 + 0.01 * (i % 7) for i in range(63)]


class PastaTemporaria:
    def criar_pasta(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.pasta, ignore_errors=True)
        self.csv = self.pasta / "landmarks.csv"
        ajuste = patch("libras.estatico.amostras.AMOSTRAS_ESTATICAS", self.csv)
        ajuste.start()
        self.addCleanup(ajuste.stop)


class AmostrasDoAlfabetoTests(PastaTemporaria, SimpleTestCase):
    def setUp(self):
        self.criar_pasta()

    def test_salva_com_cabecalho_e_conta(self):
        amostras.salvar("a", MAO)
        amostras.salvar("A", MAO)
        amostras.salvar("B", MAO)
        linhas = self.csv.read_text(encoding="utf-8").splitlines()
        self.assertEqual(linhas[0], ",".join(amostras.CABECALHO))
        self.assertEqual(len(linhas[1].split(",")), 64)
        self.assertEqual(amostras.contar(), {"A": 2, "B": 1})

    def test_mesmas_features_da_coleta(self):
        linha = amostras.salvar("C", MAO)
        valores = [float(v) for v in linha.strip().split(",")[1:]]
        self.assertEqual(valores, extrair_features_de_valores(MAO)[:63])

    def test_rejeita_letras_de_movimento_e_invalidas(self):
        for letra in ("J", "Z", "", "AB", "1", None):
            with self.assertRaises(amostras.AmostraEstaticaInvalida):
                amostras.salvar(letra, MAO)
        self.assertFalse(self.csv.exists())

    def test_rejeita_sem_mao(self):
        with self.assertRaises(amostras.AmostraEstaticaInvalida):
            amostras.salvar("A", None)

    def test_desfazer_so_a_ultima(self):
        primeira = amostras.salvar("A", MAO)
        amostras.salvar("B", MAO)
        self.assertFalse(amostras.desfazer(primeira))  # não é mais a última
        segunda = amostras.salvar("C", [v + 0.01 for v in MAO])
        self.assertTrue(amostras.desfazer(segunda))
        self.assertEqual(amostras.contar(), {"A": 1, "B": 1})
        self.assertFalse(amostras.desfazer(None))

    def test_conta_arquivo_com_bom_no_cabecalho(self):
        self.csv.write_text("﻿label,f0\r\nA,1\r\nA,2\r\nR,3\r\n", encoding="utf-8")
        self.assertEqual(amostras.contar(), {"A": 2, "R": 1})

    def test_features_de_valores_igual_ao_de_pontos(self):
        pontos = [type("P", (), {"x": MAO[i], "y": MAO[i + 1], "z": MAO[i + 2]})() for i in range(0, 63, 3)]
        self.assertEqual(extrair_features_de_valores(MAO), extrair_features(pontos))


class CameraDoAlfabetoTests(SimpleTestCase):
    def camera(self):
        camera = modulo_camera.Camera.__new__(modulo_camera.Camera)
        camera._lock = modulo_camera.threading.Lock()
        camera._ultimos_marcos = None
        return camera

    def test_marcos_recentes(self):
        camera = self.camera()
        with self.assertRaises(GravacaoIndisponivel):
            camera.marcos_recentes()
        camera._ultimos_marcos = (time.monotonic() - 5, MAO)
        with self.assertRaises(GravacaoIndisponivel):
            camera.marcos_recentes()  # mão vista há muito tempo
        camera._ultimos_marcos = (time.monotonic(), MAO)
        self.assertEqual(camera.marcos_recentes(), MAO)

    def test_recarrega_modelo_retreinado(self):
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        arquivo = pasta / "alfabeto.joblib"
        with patch("libras.captura.camera.MODEL_PATH", arquivo):
            camera = self.camera()
            camera._modelo_mtime = None
            camera._ultima_conferencia = 0.0
            camera._ultima_classificacao = 5.0
            camera._carregar_modelo()
            self.assertIsNone(camera.model)
            salvar_modelo_atomico({"versao": 1}, arquivo)
            camera._conferir_modelo(100.0)
            self.assertEqual(camera.model, {"versao": 1})
            salvar_modelo_atomico({"versao": 2}, arquivo)
            futuro = time.time() + 10
            os.utime(arquivo, (futuro, futuro))
            camera._conferir_modelo(100.5)  # dentro do intervalo: não confere
            self.assertEqual(camera.model, {"versao": 1})
            camera._conferir_modelo(103.0)
            self.assertEqual(camera.model, {"versao": 2})

    def test_salvar_modelo_atomico_nao_deixa_temporario(self):
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        arquivo = pasta / "sub" / "m.joblib"
        salvar_modelo_atomico([1, 2, 3], arquivo)
        self.assertEqual(joblib.load(arquivo), [1, 2, 3])
        self.assertEqual([p.name for p in arquivo.parent.iterdir()], ["m.joblib"])


class PaginasDoAlfabetoTests(PastaTemporaria, TestCase):
    def setUp(self):
        self.criar_pasta()
        amostras.salvar("A", MAO)

    def com_mao(self):
        ajuste = patch.object(modulo_camera.camera, "marcos_recentes", return_value=MAO)
        ajuste.start()
        self.addCleanup(ajuste.stop)

    def test_pagina_lista_letras_sem_j_e_z(self):
        response = self.client.get(reverse("alfabeto_gravar") + "?letra=b")
        letras = [item["letra"] for item in response.context["letras"]]
        self.assertNotIn("J", letras)
        self.assertNotIn("Z", letras)
        self.assertEqual(response.context["letra_inicial"], "B")
        self.assertEqual(response.context["total_amostras"], 1)
        self.assertContains(response, 'aria-current="page">Gestos', html=False)

    def test_salvar_e_desfazer_pelo_site(self):
        self.com_mao()
        resposta = self.client.post(reverse("alfabeto_amostra_salvar"), {"letra": "A"})
        self.assertEqual(resposta.json(), {"ok": True, "letra": "A", "total_letra": 2, "total": 2})
        resposta = self.client.post(reverse("alfabeto_amostra_desfazer"))
        self.assertEqual(resposta.json()["total_letra"], 1)
        # Só a última pode ser desfeita, e uma vez só.
        self.assertEqual(self.client.post(reverse("alfabeto_amostra_desfazer")).status_code, 409)

    def test_salvar_sem_mao(self):
        resposta = self.client.post(reverse("alfabeto_amostra_salvar"), {"letra": "A"})
        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(amostras.contar(), {"A": 1})

    def test_salvar_letra_de_movimento(self):
        self.com_mao()
        resposta = self.client.post(reverse("alfabeto_amostra_salvar"), {"letra": "J"})
        self.assertEqual(resposta.status_code, 400)

    def test_treinar_pelo_site(self):
        with patch("libras.views.treinar_modelo_alfabeto") as treinar:
            resposta = self.client.post(
                reverse("treinar_alfabeto"), {"voltar": reverse("alfabeto_gravar")}, follow=True
            )
        treinar.assert_called_once()
        self.assertRedirects(resposta, reverse("alfabeto_gravar"))
        self.assertContains(resposta, "Alfabeto treinado com 1 letras e 1 amostras")

    def test_treinar_com_erro(self):
        from libras.estatico.treino import ErroTreino

        with patch("libras.views.treinar_modelo_alfabeto", side_effect=ErroTreino("Colete pelo menos duas letras")):
            resposta = self.client.post(reverse("treinar_alfabeto"), follow=True)
        self.assertContains(resposta, "Não foi possível treinar o alfabeto")

    def test_gestos_mostra_painel_do_alfabeto(self):
        resposta = self.client.get(reverse("gestos"))
        self.assertContains(resposta, "Alfabeto — letras paradas")
        self.assertContains(resposta, reverse("alfabeto_gravar"))
        self.assertContains(resposta, reverse("treinar_alfabeto"))
