"""Gravação do alfabeto pelo site: amostras, classificador, páginas e treino.

Nenhum teste toca no CSV real: o arquivo de amostras é redirecionado
para uma pasta temporária (``libras.estatico.amostras.AMOSTRAS_ESTATICAS``).
"""
import json
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
from libras.estatico import amostras
from libras.estatico.classificador import (
    FORMATO_ALFABETO,
    NAO_IDENTIFICADO,
    SEM_MODELO,
    ClassificadorAlfabeto,
)
from libras.estatico.features import extrair_features, extrair_features_de_valores

from .base import entrar_como_admin

MAO = [0.5 + 0.01 * (i % 7) for i in range(63)]


class ModeloFalso:
    """RandomForest de mentira: probabilidades fixas (precisa ser picklável)."""

    def __init__(self, classes, probabilidades):
        self.classes_ = classes
        self.probabilidades = probabilidades
        self.n_jobs = -1

    def predict_proba(self, features):
        import numpy as np

        return np.array([self.probabilidades] * len(features))


def modelo_salvo(classes=("A", "B"), probabilidades=(0.9, 0.1), formato=FORMATO_ALFABETO):
    return {"formato": formato, "treinado_em": "2026-10-07T00:00:00+00:00",
            "modelo": ModeloFalso(list(classes), list(probabilidades))}


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


class ClassificadorAlfabetoTests(SimpleTestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.pasta, ignore_errors=True)
        self.arquivo = self.pasta / "alfabeto.joblib"

    def classificador(self):
        return ClassificadorAlfabeto(self.arquivo)

    def test_sem_modelo(self):
        classificador = self.classificador()
        self.assertFalse(classificador.pronto)
        self.assertEqual(classificador.classificar(MAO), SEM_MODELO)
        self.assertIsNone(classificador.erro)

    def test_reconhece_e_respeita_o_limiar(self):
        salvar_modelo_atomico(modelo_salvo(probabilidades=(0.9, 0.1)), self.arquivo)
        classificador = self.classificador()
        self.assertTrue(classificador.pronto)
        self.assertEqual(classificador.letras, ["A", "B"])
        self.assertEqual(classificador.modelo.n_jobs, 1)
        self.assertEqual(classificador.classificar(MAO), "A")
        salvar_modelo_atomico(modelo_salvo(probabilidades=(0.6, 0.4)), self.arquivo)
        self.assertEqual(self.classificador().classificar(MAO), NAO_IDENTIFICADO)

    def test_modelo_do_formato_antigo_e_ignorado(self):
        # Antes o modelo era salvo puro (sem dicionário) e com pontos da câmera do servidor.
        salvar_modelo_atomico(ModeloFalso(["A"], [1.0]), self.arquivo)
        classificador = self.classificador()
        self.assertFalse(classificador.pronto)
        self.assertIn("versão antiga", classificador.erro)
        salvar_modelo_atomico(modelo_salvo(formato=2), self.arquivo)
        self.assertFalse(self.classificador().pronto)

    def test_recarrega_modelo_retreinado(self):
        salvar_modelo_atomico(modelo_salvo(classes=("A", "B")), self.arquivo)
        classificador = self.classificador()
        self.assertEqual(classificador.letras, ["A", "B"])
        salvar_modelo_atomico(modelo_salvo(classes=("C", "D")), self.arquivo)
        futuro = time.time() + 10
        os.utime(self.arquivo, (futuro, futuro))
        classificador.conferir()  # dentro do intervalo: não confere
        self.assertEqual(classificador.letras, ["A", "B"])
        classificador._conferido_em -= 3
        self.assertEqual(classificador.classificar(MAO), "C")

    def test_modelo_apagado_deixa_de_reconhecer_sem_reiniciar(self):
        salvar_modelo_atomico(modelo_salvo(), self.arquivo)
        classificador = self.classificador()
        self.assertTrue(classificador.pronto)
        self.arquivo.unlink()  # "recomeçar do zero"
        classificador._conferido_em -= 3
        self.assertFalse(classificador.pronto)
        self.assertEqual(classificador.classificar(MAO), SEM_MODELO)

    def test_treino_real_e_aceito(self):
        from libras.estatico.treino import treinar

        csv = self.pasta / "alfabeto.csv"
        for indice, letra in enumerate("AB"):
            for passo in range(10):
                amostras.salvar(letra, [0.3 + 0.2 * indice + 0.001 * passo + 0.001 * (i % 5) for i in range(63)], csv)
        treinar(csv, self.arquivo)
        classificador = self.classificador()
        self.assertEqual(classificador.letras, ["A", "B"])
        self.assertIn(classificador.classificar([0.3 + 0.001 * (i % 5) for i in range(63)]), ("A", NAO_IDENTIFICADO))

    def test_carrega_o_arquivo_padrao_na_hora(self):
        salvar_modelo_atomico(modelo_salvo(), self.arquivo)
        with patch("libras.caminhos.MODELO_ALFABETO", self.arquivo):
            self.assertTrue(ClassificadorAlfabeto().pronto)

    def test_salvar_modelo_atomico_nao_deixa_temporario(self):
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        arquivo = pasta / "sub" / "m.joblib"
        salvar_modelo_atomico([1, 2, 3], arquivo)
        self.assertEqual(joblib.load(arquivo), [1, 2, 3])
        self.assertEqual([p.name for p in arquivo.parent.iterdir()], ["m.joblib"])


class PaginasDoAlfabetoTests(PastaTemporaria, TestCase):
    def setUp(self):
        entrar_como_admin(self)
        self.criar_pasta()
        amostras.salvar("A", MAO)

    def salvar(self, letra, marcos=MAO):
        return self.client.post(
            reverse("alfabeto_amostra_salvar"),
            json.dumps({"letra": letra, "marcos": marcos}),
            content_type="application/json",
        )

    def test_pagina_lista_letras_sem_j_e_z(self):
        response = self.client.get(reverse("alfabeto_gravar") + "?letra=b")
        letras = [item["letra"] for item in response.context["letras"]]
        self.assertNotIn("J", letras)
        self.assertNotIn("Z", letras)
        self.assertEqual(response.context["letra_inicial"], "B")
        self.assertEqual(response.context["total_amostras"], 1)
        self.assertContains(response, 'aria-current="page">Gestos', html=False)

    def test_salvar_e_desfazer_pelo_site(self):
        resposta = self.salvar("A")
        self.assertEqual(resposta.json(), {"ok": True, "letra": "A", "total_letra": 2, "total": 2})
        resposta = self.client.post(reverse("alfabeto_amostra_desfazer"))
        self.assertEqual(resposta.json()["total_letra"], 1)
        # Só a última pode ser desfeita, e uma vez só.
        self.assertEqual(self.client.post(reverse("alfabeto_amostra_desfazer")).status_code, 409)

    def test_salvar_sem_mao_ou_com_pontos_invalidos(self):
        for marcos in (None, [0.5] * 10, ["x"] * 63, [50.0] * 63):
            with self.subTest(marcos=str(marcos)[:20]):
                self.assertEqual(self.salvar("A", marcos).status_code, 400)
        resposta = self.client.post(reverse("alfabeto_amostra_salvar"), "nada", content_type="application/json")
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(amostras.contar(), {"A": 1})

    def test_salvar_letra_de_movimento(self):
        resposta = self.salvar("J")
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

    def test_pagina_usa_a_camera_do_navegador(self):
        resposta = self.client.get(reverse("alfabeto_gravar"))
        self.assertContains(resposta, 'id="video"')
        self.assertContains(resposta, "js/camera-maos.js")
        self.assertContains(resposta, reverse("api_quadros"))

    def test_gestos_mostra_painel_do_alfabeto(self):
        resposta = self.client.get(reverse("gestos"))
        self.assertContains(resposta, "Alfabeto — letras paradas")
        self.assertContains(resposta, reverse("alfabeto_gravar"))
        self.assertContains(resposta, reverse("treinar_alfabeto"))


def mao(semente):
    """63 valores de uma mão de teste; sementes diferentes, mãos diferentes."""
    import random

    gerador = random.Random(semente)
    return [0.5 + gerador.uniform(-0.2, 0.2) for _ in range(63)]


class ApagarAmostrasDoAlfabetoTests(PastaTemporaria, SimpleTestCase):
    def setUp(self):
        self.criar_pasta()
        self.linhas_a = [amostras.salvar("A", mao(k / 100)) for k in range(4)]
        amostras.salvar("B", mao(0.5))

    def test_lista_so_a_letra_em_ordem(self):
        lista = amostras.listar("a")
        self.assertEqual([item["numero"] for item in lista], [1, 2, 3, 4])
        self.assertEqual(len(lista[0]["valores"]), 63)
        self.assertEqual(len({item["id"] for item in lista}), 4)
        self.assertEqual(lista[0]["id"], amostras.id_da_linha(self.linhas_a[0]) + "-1")
        self.assertEqual(amostras.listar("C"), [])

    def test_apaga_as_escolhidas_e_mantem_o_resto(self):
        lista = amostras.listar("A")
        self.assertEqual(amostras.apagar("A", [lista[0]["id"], lista[2]["id"]]), 2)
        self.assertEqual([item["id"] for item in amostras.listar("A")], [lista[1]["id"], lista[3]["id"]])
        self.assertEqual(amostras.contar(), {"A": 2, "B": 1})
        # Cabeçalho intacto e nada de arquivo temporário sobrando.
        self.assertTrue(self.csv.read_text(encoding="utf-8").startswith("label,f0,"))
        self.assertEqual([p.name for p in self.pasta.iterdir()], ["landmarks.csv"])

    def test_id_de_outra_letra_ou_inexistente_nao_apaga(self):
        id_b = amostras.listar("B")[0]["id"]
        self.assertEqual(amostras.apagar("A", [id_b, "naoexiste123"]), 0)
        self.assertEqual(amostras.apagar("A", []), 0)
        self.assertEqual(amostras.contar(), {"A": 4, "B": 1})

    def test_ids_continuam_validos_com_gravacoes_novas(self):
        alvo = amostras.listar("A")[1]["id"]
        amostras.apagar("A", [amostras.listar("A")[0]["id"]])  # posições mudam
        amostras.salvar("A", mao(0.9))  # alguém gravou ao mesmo tempo
        self.assertEqual(amostras.apagar("A", [alvo]), 1)
        self.assertNotIn(alvo, [item["id"] for item in amostras.listar("A")])

    def test_amostras_identicas_sao_apagadas_uma_de_cada_vez(self):
        repetida = mao(42)
        amostras.salvar("C", repetida)
        amostras.salvar("C", repetida)  # Espaço duas vezes na mesma imagem
        primeira, segunda = amostras.listar("C")
        self.assertNotEqual(primeira["id"], segunda["id"])
        self.assertEqual(amostras.apagar("C", [segunda["id"]]), 1)
        self.assertEqual(amostras.contar()["C"], 1)

    def test_desfazer_continua_funcionando_depois_de_apagar(self):
        ultima = amostras.salvar("A", mao(0.7))
        amostras.apagar("A", [amostras.listar("A")[0]["id"]])
        self.assertTrue(amostras.desfazer(ultima))
        self.assertEqual(amostras.contar(), {"A": 3, "B": 1})


class PaginaDaLetraTests(PastaTemporaria, TestCase):
    def setUp(self):
        entrar_como_admin(self)
        self.criar_pasta()
        for k in range(3):
            amostras.salvar("A", mao(k / 100))
        amostras.salvar("B", mao(0.5))

    def test_mostra_cada_amostra_desenhada(self):
        resposta = self.client.get(reverse("alfabeto_letra", args=["a"]))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context["amostras"]), 3)
        self.assertContains(resposta, 'class="amostra-mao"', count=3)
        self.assertContains(resposta, "<line ", count=3 * 21)
        # Coordenadas com ponto decimal (o pt-BR usaria vírgula e o SVG não desenharia).
        import re
        self.assertFalse(re.search(r'<line x1="\d+,\d', resposta.content.decode()))
        self.assertTrue(re.search(r'<line x1="\d+(\.\d)?" ', resposta.content.decode()))
        self.assertContains(resposta, 'id="selecionar-todas"')
        self.assertContains(resposta, "js/selecao-amostras.js")
        for x in [p["x"] for p in resposta.context["amostras"][0]["desenho"]["pontos"]]:
            self.assertTrue(0 <= x <= 100)

    def test_letra_invalida_ou_de_movimento(self):
        self.assertEqual(self.client.get("/gestos/alfabeto/J/").status_code, 404)
        self.assertEqual(self.client.get("/gestos/alfabeto/1/").status_code, 404)
        # As rotas vizinhas continuam funcionando (não são confundidas com uma letra).
        self.assertEqual(self.client.get(reverse("alfabeto_gravar")).status_code, 200)
        self.assertEqual(self.client.post(reverse("alfabeto_amostra_desfazer")).status_code, 409)

    def test_apagar_selecionadas_e_todas(self):
        ids = [item["id"] for item in amostras.listar("A")]
        url = reverse("alfabeto_amostras_apagar", args=["A"])
        resposta = self.client.post(url, {"amostra": ids[:1]}, follow=True)
        self.assertRedirects(resposta, reverse("alfabeto_letra", args=["A"]))
        self.assertContains(resposta, "1 amostra da letra A apagada")
        resposta = self.client.post(url, {"amostra": ids[1:]}, follow=True)
        self.assertContains(resposta, "2 amostras da letra A apagadas")
        self.assertContains(resposta, "Nenhuma amostra da letra A")
        self.assertEqual(amostras.contar(), {"B": 1})

    def test_apagar_sem_selecao(self):
        resposta = self.client.post(reverse("alfabeto_amostras_apagar", args=["A"]), follow=True)
        self.assertContains(resposta, "Nenhuma amostra apagada")
        self.assertEqual(amostras.contar(), {"A": 3, "B": 1})

    def test_so_admin_e_so_post(self):
        url = reverse("alfabeto_amostras_apagar", args=["A"])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        ids = [item["id"] for item in amostras.listar("A")]
        self.assertEqual(self.client.post(url, {"amostra": ids}).status_code, 302)
        self.assertEqual(self.client.get(reverse("alfabeto_letra", args=["A"])).status_code, 302)
        self.assertEqual(amostras.contar(), {"A": 3, "B": 1})

    def test_atalhos_para_a_pagina_da_letra(self):
        gestos = self.client.get(reverse("gestos"))
        self.assertContains(gestos, f'href="{reverse("alfabeto_letra", args=["A"])}"')
        gravar = self.client.get(reverse("alfabeto_gravar") + "?letra=B")
        self.assertContains(gravar, 'id="ver-amostras"')
        self.assertContains(gravar, reverse("alfabeto_letra", args=["B"]))
