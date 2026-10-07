"""Excluir um sinal inteiro: cadastro, amostras, arquivos e o que o modelo aprendeu."""
from pathlib import Path

import joblib
from django.urls import reverse

from libras.models import AmostraMovimento, Sinal
from libras.movimento import classificador
from libras.movimento.classificador import prever

from .base import TemporalMLBase


class RemoverDoModeloTests(TemporalMLBase):
    def treinar_dois(self):
        """Modelo com J e K; devolve o sinal K."""
        k = Sinal.objects.create(titulo="K", tipo=Sinal.Tipo.MOVIMENTO)
        for fase in (2.0, 2.05, 2.1):
            self.salvar_trajetoria(k, self.trajetoria_sintetica(fase=fase))
        self.treinar_padrao(self.sinal)
        return k

    def test_remove_so_o_sinal_pedido(self):
        k = self.treinar_dois()
        antes = classificador.carregar_modelo()
        self.assertEqual(
            classificador.remover_do_modelo(self.sinal.pk, "J"), "removido"
        )
        depois = classificador.carregar_modelo()
        self.assertEqual(depois["classes"], ["K"])
        self.assertNotIn("J", depois["templates"])
        # O outro sinal fica exatamente como estava (sem retreino).
        self.assertEqual(depois["limiares"]["K"], antes["limiares"]["K"])
        self.assertEqual(depois["templates"]["K"], antes["templates"]["K"])
        self.assertEqual(depois["sinal_id"], {"K": k.pk})
        trajetoria = depois["templates"]["K"][0]["trajetoria"]
        self.assertEqual(prever(trajetoria, depois)["previsto"], "K")

    def test_ultimo_sinal_apaga_o_modelo(self):
        self.treinar_padrao(self.sinal)
        self.assertEqual(
            classificador.remover_do_modelo(self.sinal.pk, "J"), "modelo_apagado"
        )
        self.assertFalse(Path(classificador.MODELO_PATH).exists())

    def test_remove_exemplo_negativo(self):
        negativo = Sinal.objects.create(
            titulo="J incompleto", tipo=Sinal.Tipo.MOVIMENTO, negativo=True
        )
        self.salvar_trajetoria(negativo, self.trajetoria_sintetica(fase=0.9))
        self.treinar_padrao(self.sinal)
        self.assertEqual(
            classificador.remover_do_modelo(negativo.pk, "J incompleto"), "removido"
        )
        modelo = classificador.carregar_modelo()
        self.assertEqual(modelo["negativos"], [])
        self.assertEqual(modelo["classes"], ["J"])

    def test_negativo_de_modelo_antigo_e_achado_pelo_titulo(self):
        negativo = Sinal.objects.create(
            titulo="I parado", tipo=Sinal.Tipo.MOVIMENTO, negativo=True
        )
        self.salvar_trajetoria(negativo, self.trajetoria_sintetica(fase=0.9))
        self.treinar_padrao(self.sinal)
        modelo = classificador.carregar_modelo()
        for entrada in modelo["negativos"]:
            del entrada["sinal_id"]  # como nos modelos antigos
        joblib.dump(modelo, classificador.MODELO_PATH)
        self.assertEqual(
            classificador.remover_do_modelo(negativo.pk, "I parado"), "removido"
        )
        self.assertEqual(classificador.carregar_modelo()["negativos"], [])

    def test_sinal_fora_do_modelo(self):
        self.treinar_padrao(self.sinal)
        outro = Sinal.objects.create(titulo="Z", tipo=Sinal.Tipo.MOVIMENTO)
        self.assertIsNone(classificador.remover_do_modelo(outro.pk, "Z"))
        self.assertIsNone(classificador.remover_do_modelo(999, "?"))

    def test_sem_modelo(self):
        self.assertIsNone(classificador.remover_do_modelo(self.sinal.pk, "J"))


class ExcluirSinalPeloSiteTests(TemporalMLBase):
    def test_detalhe_tem_botao_e_janela_de_confirmacao(self):
        self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica())
        response = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertContains(response, "Excluir sinal")
        self.assertContains(response, 'id="janela-excluir"')
        self.assertContains(response, "Tem certeza que deseja excluir o sinal <strong>J</strong>?", html=False)
        self.assertContains(response, "Sim, excluir")
        self.assertContains(response, 'class="botao-nao"')

    def test_pagina_de_confirmacao_nao_exclui(self):
        for fase in (0.0, 0.05):
            self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica(fase=fase))
        response = self.client.get(reverse("gesto_excluir", args=[self.sinal.pk]))
        self.assertContains(response, "todas as 2")
        self.assertContains(response, "e o treinamento dele")
        self.assertTrue(Sinal.objects.filter(pk=self.sinal.pk).exists())

    def test_exclui_sinal_amostras_arquivos_e_treinamento(self):
        _, pks = self.treinar_padrao(self.sinal)
        z = Sinal.objects.create(titulo="Z", tipo=Sinal.Tipo.MOVIMENTO)
        amostra_z = self.salvar_trajetoria(z, self.trajetoria_sintetica(fase=3.0))
        arquivos = [Path(self.media_tmp) / a.arquivo_dados for a in AmostraMovimento.objects.filter(sinal=self.sinal)]
        pasta = arquivos[0].parent
        response = self.client.post(reverse("gesto_excluir", args=[self.sinal.pk]), follow=True)
        self.assertRedirects(response, reverse("gestos"))
        self.assertContains(response, "Sinal J excluído, com 5 amostras.")
        self.assertContains(response, "último sinal do modelo")
        self.assertFalse(Sinal.objects.filter(pk=self.sinal.pk).exists())
        self.assertFalse(AmostraMovimento.objects.filter(pk__in=pks).exists())
        self.assertFalse(any(a.exists() for a in arquivos))
        self.assertFalse(pasta.exists())
        self.assertFalse(Path(classificador.MODELO_PATH).exists())
        # O outro sinal e as amostras dele continuam.
        self.assertTrue(AmostraMovimento.objects.filter(pk=amostra_z.pk).exists())
        self.assertTrue((Path(self.media_tmp) / amostra_z.arquivo_dados).exists())

    def test_exclui_sinal_estatico(self):
        estatico = Sinal.objects.create(titulo="I")
        response = self.client.get(reverse("gesto_excluir", args=[estatico.pk]))
        self.assertContains(response, "sinal estático")
        response = self.client.post(reverse("gesto_excluir", args=[estatico.pk]), follow=True)
        self.assertContains(response, "Sinal I excluído.")
        self.assertFalse(Sinal.objects.filter(pk=estatico.pk).exists())

    def test_sinal_inexistente(self):
        self.assertEqual(self.client.post(reverse("gesto_excluir", args=[999])).status_code, 404)
