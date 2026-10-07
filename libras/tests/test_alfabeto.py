"""Alfabeto estático: features, treino e comandos (sem webcam)."""
import json
import random
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import joblib
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from libras.estatico.features import extrair_features, features_geometricas
from libras.estatico.treino import ErroTreino, treinar
from libras.estatico.amostras import CABECALHO, AmostraEstaticaInvalida, validar_letra
from libras.estatico.classificador import FORMATO_ALFABETO
from libras.movimento.verificacao import verificar_conteudo


def ponto(x, y, z=0.0):
    return type("P", (), {"x": x, "y": y, "z": z})()


class FeaturesAlfabetoTests(SimpleTestCase):
    def test_63_coordenadas_mais_10_distancias(self):
        mao = [ponto(0.5 + 0.01 * i, 0.5 - 0.02 * i, 0.001 * i) for i in range(21)]
        features = extrair_features(mao)
        self.assertEqual(len(features), 63 + 10)
        # Pulso na origem: as três primeiras coordenadas são zero.
        self.assertEqual(features[:3], [0.0, 0.0, 0.0])
        self.assertEqual(features[63:], features_geometricas(features[:63]))

    def test_invariante_a_posicao_da_mao(self):
        mao = [ponto(0.3 + 0.01 * i, 0.4 + 0.015 * i) for i in range(21)]
        deslocada = [ponto(p.x + 0.2, p.y - 0.1) for p in mao]
        for a, b in zip(extrair_features(mao), extrair_features(deslocada)):
            self.assertAlmostEqual(a, b)


class TreinoAlfabetoTests(SimpleTestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.pasta, ignore_errors=True)

    def escrever_dataset(self, letras="AB", por_letra=10):
        gerador = random.Random(3)
        linhas = [",".join(CABECALHO)]
        for indice, letra in enumerate(letras):
            for _ in range(por_letra):
                valores = [indice + gerador.uniform(-0.1, 0.1) for _ in range(63)]
                linhas.append(",".join([letra, *map(str, valores)]))
        caminho = self.pasta / "landmarks.csv"
        caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        return caminho

    def test_treina_e_salva_modelo(self):
        destino = self.pasta / "modelos" / "alfabeto.joblib"
        relatorio = treinar(self.escrever_dataset(), destino)
        self.assertIn("precision", relatorio)
        salvo = joblib.load(destino)
        self.assertEqual(salvo["formato"], FORMATO_ALFABETO)
        self.assertIn("treinado_em", salvo)
        self.assertEqual(sorted(salvo["modelo"].classes_), ["A", "B"])

    def test_dataset_ausente(self):
        with self.assertRaises(ErroTreino) as contexto:
            treinar(self.pasta / "nao_existe.csv", self.pasta / "m.joblib")
        self.assertIn("Grave as letras pelo site", str(contexto.exception))

    def test_uma_letra_so_nao_treina(self):
        with self.assertRaises(ErroTreino):
            treinar(self.escrever_dataset(letras="A"), self.pasta / "m.joblib")

    def test_comando_relata_erro(self):
        def falha():
            raise ErroTreino("Colete pelo menos duas letras antes de treinar.")

        with patch("libras.management.commands.treinar_alfabeto.treinar", falha):
            with self.assertRaises(CommandError):
                call_command("treinar_alfabeto", stdout=StringIO())


class ComandosAlfabetoTests(SimpleTestCase):
    def test_valida_letra(self):
        self.assertEqual(validar_letra(" a "), "A")
        for invalida in ("", "AB", "1", None):
            with self.assertRaises(AmostraEstaticaInvalida):
                validar_letra(invalida)

    def test_gera_nao_j_sintetico_valido(self):
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        saida = pasta / "nao_j.json"
        call_command("gerar_nao_j_sintetico", saida=str(saida), stdout=StringIO())
        conteudo = json.loads(saida.read_text(encoding="utf-8"))
        self.assertEqual(conteudo["origem"], "sintetico")
        self.assertTrue(verificar_conteudo(conteudo).ok)
