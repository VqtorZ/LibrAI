"""Páginas: home com dados reais, Gestos, página do sinal, treino pelo site e menu."""
from django.urls import reverse

from libras.models import Sinal
from libras.movimento import classificador

from .base import TemporalMLBase


class SituacaoDosSinaisTests(TemporalMLBase):
    """Situação de cada sinal de movimento frente ao modelo treinado."""

    def situacao(self, sinal):
        return classificador.situacao_dos_sinais([sinal])[sinal.pk]["codigo"]

    def test_sem_amostras(self):
        self.assertEqual(self.situacao(self.sinal), "sem_amostras")

    def test_uma_amostra_nao_basta(self):
        self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica())
        self.assertEqual(self.situacao(self.sinal), "poucas")

    def test_negativo_com_uma_amostra_pode_treinar(self):
        negativo = Sinal.objects.create(
            titulo="I parado", tipo=Sinal.Tipo.MOVIMENTO, negativo=True
        )
        self.salvar_trajetoria(negativo, self.trajetoria_sintetica(fase=2.0))
        self.assertEqual(self.situacao(negativo), "treinar")

    def test_pronto_depois_de_treinar_e_treinar_apos_nova_amostra(self):
        self.treinar_padrao(self.sinal)
        self.assertEqual(self.situacao(self.sinal), "pronto")
        self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica(fase=0.3))
        self.assertEqual(self.situacao(self.sinal), "treinar")

    def test_amostra_apagada_pede_novo_treino(self):
        _, pks = self.treinar_padrao(self.sinal)
        self.sinal.amostras.get(pk=pks[0]).delete()
        self.assertEqual(self.situacao(self.sinal), "treinar")

    def test_negativo_entra_no_modelo(self):
        negativo = Sinal.objects.create(
            titulo="J incompleto", tipo=Sinal.Tipo.MOVIMENTO, negativo=True
        )
        self.salvar_trajetoria(negativo, self.trajetoria_sintetica(fase=2.0))
        self.treinar_padrao(self.sinal)
        self.assertEqual(self.situacao(negativo), "pronto")


class TreinarPeloSiteTests(TemporalMLBase):
    """Botão "Treinar reconhecimento": mesmo treino do comando."""

    def test_treina_e_volta_com_mensagem(self):
        self.treinar_padrao(self.sinal)  # cria as amostras
        voltar = reverse("gesto_detalhe", args=[self.sinal.pk])
        response = self.client.post(
            reverse("treinar_movimentos"), {"voltar": voltar}, follow=True
        )
        self.assertRedirects(response, voltar)
        self.assertContains(response, "Modelo treinado: J (5 amostras)")
        self.assertContains(response, "No reconhecimento")

    def test_sem_amostras_mostra_erro(self):
        response = self.client.post(reverse("treinar_movimentos"), follow=True)
        self.assertRedirects(response, reverse("gestos"))
        self.assertContains(response, "Não foi possível treinar")

    def test_avisa_sinal_que_ficou_de_fora(self):
        self.treinar_padrao(self.sinal)
        outro = Sinal.objects.create(titulo="Z", tipo=Sinal.Tipo.MOVIMENTO)
        self.salvar_trajetoria(outro, self.trajetoria_sintetica(fase=3.0))
        response = self.client.post(reverse("treinar_movimentos"), follow=True)
        self.assertContains(response, "Z ficou de fora")

    def test_nao_redireciona_para_outro_site(self):
        self.treinar_padrao(self.sinal)
        response = self.client.post(
            reverse("treinar_movimentos"), {"voltar": "https://exemplo.com/"}
        )
        self.assertRedirects(response, reverse("gestos"), fetch_redirect_response=False)

    def test_exige_post(self):
        self.assertEqual(self.client.get(reverse("treinar_movimentos")).status_code, 405)


class PaginasDeGestosTests(TemporalMLBase):
    def test_lista_mostra_amostras_e_situacao(self):
        self.treinar_padrao(self.sinal)
        Sinal.objects.create(titulo="Z", tipo=Sinal.Tipo.MOVIMENTO)
        response = self.client.get(reverse("gestos"))
        self.assertContains(response, "<strong>5</strong> amostras", html=False)
        self.assertContains(response, "No reconhecimento")
        self.assertContains(response, "Sem amostras")
        self.assertNotContains(response, "Há sinais com amostras novas")

    def test_lista_avisa_quando_precisa_treinar(self):
        for fase in (0.0, 0.05):
            self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica(fase=fase))
        response = self.client.get(reverse("gestos"))
        self.assertContains(response, "Há sinais com amostras novas")
        self.assertContains(response, reverse("treinar_movimentos"))

    def test_detalhe_mostra_resumo_e_botao_de_treino(self):
        for fase in (0.0, 0.05):
            self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica(fase=fase))
        response = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertContains(response, "Precisa treinar")
        self.assertContains(response, "duração média")
        self.assertContains(response, "Treinar reconhecimento")

    def test_formulario_esconde_negativo_para_estatico(self):
        response = self.client.get(reverse("gesto_novo"))
        self.assertContains(response, 'id="campo-negativo"')
        self.assertContains(response, "tipo.value === 'MOVIMENTO'", html=False)


class HomeTests(TemporalMLBase):
    def test_mostra_o_que_reconhece_de_verdade(self):
        self.treinar_padrao(self.sinal)  # modelo de movimento com a classe J
        response = self.client.get(reverse("inicio"))
        alfabeto = {item["letra"]: item["tipo"] for item in response.context["alfabeto"]}
        self.assertEqual(alfabeto["J"], "movimento")
        self.assertEqual(response.context["total_movimento"], 1)
        self.assertEqual(response.context["total_amostras"], 5)
        self.assertIn("J", response.context["letras_demo"])
        self.assertContains(response, "Sua mão fala.")
        self.assertContains(response, 'id="letras-demo"')

    def test_sem_modelo_de_movimento(self):
        response = self.client.get(reverse("inicio"))
        self.assertEqual(response.context["total_movimento"], 0)
        self.assertNotIn(
            "movimento", {item["tipo"] for item in response.context["alfabeto"]}
        )


class MenuEEstilosTests(TemporalMLBase):
    def test_menu_marca_a_pagina_atual(self):
        response = self.client.get(reverse("gestos"))
        self.assertContains(
            response, f'<a href="{reverse("gestos")}" class="is-active" aria-current="page">', html=False
        )
        response = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertContains(response, 'aria-current="page">Gestos', html=False)
        response = self.client.get(reverse("inicio"))
        self.assertNotContains(response, 'aria-current="page"')

    def test_link_pular_para_o_conteudo(self):
        response = self.client.get(reverse("gestos"))
        self.assertContains(response, 'href="#conteudo"')
        self.assertContains(response, 'id="conteudo"')

    def test_css_com_versao_para_nao_usar_cache_velho(self):
        response = self.client.get(reverse("gestos"))
        versao = response.context["versao_estaticos"]
        self.assertGreater(versao, 0)
        self.assertContains(response, f"css/app.css?v={versao}")
