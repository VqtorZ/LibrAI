"""Cadastro de sinais: model, formulário, páginas, admin e rotas."""
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from libras.forms import SinalForm
from libras.models import AmostraMovimento, Sinal
from libras.movimento.amostras import (
    FORMATO_VERSAO,
    salvar_amostra,
)

from .base import entrar_como_admin, TemporalBase


class SinalModelTests(TestCase):
    def test_criacao_com_defaults(self):
        sinal = Sinal.objects.create(titulo="Obrigado", descricao="Sinal de agradecimento")
        self.assertEqual(str(sinal), "Obrigado")
        self.assertTrue(sinal.ativo)
        self.assertIsNotNone(sinal.criado_em)
        self.assertIsNotNone(sinal.atualizado_em)

    def test_descricao_opcional(self):
        sinal = Sinal.objects.create(titulo="Bom dia")
        self.assertEqual(sinal.descricao, "")

    def test_desativacao(self):
        sinal = Sinal.objects.create(titulo="Eu")
        sinal.ativo = False
        sinal.save()
        self.assertFalse(Sinal.objects.get(pk=sinal.pk).ativo)


class SinalFormTests(TestCase):
    def test_titulo_obrigatorio_com_mensagem_amigavel(self):
        form = SinalForm(data={"titulo": "   ", "descricao": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("Informe o título do sinal.", form.errors["titulo"])

    def test_titulo_com_espacos_desnecessarios(self):
        form = SinalForm(data={"titulo": "  Nome Leonardo  ", "descricao": ""})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["titulo"], "Nome Leonardo")

    def test_descricao_opcional(self):
        form = SinalForm(data={"titulo": "Obrigado"})
        self.assertTrue(form.is_valid())

    def test_salva_no_banco(self):
        form = SinalForm(data={"titulo": "Você", "descricao": "Sinal de segunda pessoa"})
        self.assertTrue(form.is_valid())
        sinal = form.save()
        self.assertEqual(Sinal.objects.count(), 1)
        self.assertEqual(sinal.titulo, "Você")
        self.assertTrue(sinal.ativo)


class GestosViewsTests(TestCase):
    def setUp(self):
        entrar_como_admin(self)

    def test_lista_apenas_sinais_ativos(self):
        Sinal.objects.create(titulo="Obrigado")
        Sinal.objects.create(titulo="Desativado", ativo=False)
        response = self.client.get(reverse("gestos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Obrigado")
        self.assertNotContains(response, "Desativado")

    def test_lista_vazia_exibe_mensagem_amigavel(self):
        response = self.client.get(reverse("gestos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ainda não existem sinais cadastrados")

    def test_formulario_carrega(self):
        response = self.client.get(reverse("gesto_novo"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Título do sinal")

    def test_cadastro_valido_redireciona_e_salva(self):
        response = self.client.post(
            reverse("gesto_novo"),
            {"titulo": "Nome Leonardo", "descricao": "Sinal do nome Leonardo"},
        )
        self.assertRedirects(response, reverse("gestos"))
        sinal = Sinal.objects.get(titulo="Nome Leonardo")
        self.assertTrue(sinal.ativo)
        self.assertEqual(sinal.descricao, "Sinal do nome Leonardo")

    def test_cadastro_invalido_permanece_com_erros(self):
        response = self.client.post(reverse("gesto_novo"), {"titulo": "", "descricao": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informe o título do sinal.")
        self.assertEqual(Sinal.objects.count(), 0)

    def test_cadastro_exibe_mensagem_de_sucesso(self):
        response = self.client.post(
            reverse("gesto_novo"), {"titulo": "Bom dia"}, follow=True
        )
        self.assertContains(response, "Sinal cadastrado com sucesso.")


class SinalAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin", "admin@example.com", "senha-teste")

    def test_lista_no_admin(self):
        Sinal.objects.create(titulo="Obrigado")
        self.client.force_login(self.admin)
        response = self.client.get("/admin/libras/sinal/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Obrigado")

    def test_pagina_de_cadastro_no_admin(self):
        self.client.force_login(self.admin)
        response = self.client.get("/admin/libras/sinal/add/")
        self.assertEqual(response.status_code, 200)


class RotasExistentesTests(TestCase):
    """Garante que as rotas originais continuam funcionando."""

    def test_home(self):
        response = self.client.get(reverse("inicio"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LibrAI")

    def test_recognizer(self):
        response = self.client.get(reverse("reconhecer"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="label"')

    def test_api_quadros(self):
        response = self.client.post(
            reverse("api_quadros"),
            {"canal": "teste-sinais-1", "quadros": [{"t": 0, "marcos": None}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("label", payload)
        self.assertNotIn("error", payload)
        # Verdadeiro só quando há um modelo do alfabeto treinado.
        self.assertIsInstance(payload["model_ready"], bool)


class SinalTipoTests(TestCase):
    """O sinal agora nasce com um tipo: estático (default) ou movimento."""

    def setUp(self):
        entrar_como_admin(self)

    def test_tipo_padrao_e_estatico(self):
        sinal = Sinal.objects.create(titulo="A")
        self.assertEqual(sinal.tipo, Sinal.Tipo.ESTATICO)

    def test_tipo_movimento_explicito(self):
        sinal = Sinal.objects.create(titulo="J", tipo=Sinal.Tipo.MOVIMENTO)
        self.assertEqual(sinal.tipo, Sinal.Tipo.MOVIMENTO)
        self.assertEqual(sinal.get_tipo_display(), "Movimento")

    def test_form_salva_tipo_movimento(self):
        form = SinalForm(data={"titulo": "J", "tipo": Sinal.Tipo.MOVIMENTO})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.save().tipo, Sinal.Tipo.MOVIMENTO)

    def test_form_sem_tipo_mantem_compatibilidade(self):
        form = SinalForm(data={"titulo": "Obrigado"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.save().tipo, Sinal.Tipo.ESTATICO)

    def test_form_rejeita_tipo_invalido(self):
        form = SinalForm(data={"titulo": "X", "tipo": "DINAMICO"})
        self.assertFalse(form.is_valid())

    def test_formulario_oferece_os_dois_tipos(self):
        response = self.client.get(reverse("gesto_novo"))
        self.assertContains(response, "Tipo do sinal")
        self.assertContains(response, "Estático")
        self.assertContains(response, "Movimento")


class GestoDetalheEGravarTests(TemporalBase):
    """Rotas novas: detalhe do sinal e estúdio de gravação."""

    def test_detalhe_exibe_sinal(self):
        response = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.sinal.titulo)
        self.assertContains(response, "Gravar nova amostra")
        self.assertContains(response, "Ainda não há amostras gravadas")

    def test_detalhe_lista_amostras(self):
        amostra = AmostraMovimento.objects.create(
            sinal=self.sinal, quantidade_frames=42, duracao_ms=2800,
            arquivo_dados="movimentos/1/1.json", fps=15.0, versao_features=FORMATO_VERSAO,
        )
        response = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        # Resumo no topo e uma linha por amostra na tabela.
        self.assertContains(response, 'class="resumo-rotulo">amostra<')
        self.assertContains(response, "2,8 s")  # formato brasileiro
        self.assertContains(response, f'<th scope="row">#{amostra.pk}</th>', html=False)
        self.assertContains(response, "<td>42</td>", html=False)

    def test_amostras_antigas_ficam_de_fora_e_pedem_regravar(self):
        for _ in range(2):
            AmostraMovimento.objects.create(
                sinal=self.sinal, quantidade_frames=30, duracao_ms=1000,
                arquivo_dados="antigo.json", fps=30.0, versao_features=2,
            )
        response = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertEqual(len(response.context["amostras"]), 0)
        self.assertEqual(response.context["situacao"]["codigo"], "regravar")
        self.assertContains(response, "situacao--regravar")
        self.assertContains(response, "2 amostras")
        self.assertContains(response, "fora do")
        # A exclusão do sinal avisa que as antigas também vão embora.
        self.assertContains(response, "todas as 2")
        lista = self.client.get(reverse("gestos"))
        self.assertContains(lista, "Regravar")

    def test_detalhe_de_sinal_inexistente_retorna_404(self):
        response = self.client.get(reverse("gesto_detalhe", args=[9999]))
        self.assertEqual(response.status_code, 404)

    def test_gravar_abre_para_sinal_de_movimento(self):
        response = self.client.get(reverse("gesto_gravar", args=[self.sinal.pk]))
        self.assertEqual(response.status_code, 200)
        # Câmera do navegador, com gravação pelo Espaço.
        self.assertContains(response, 'id="video"')
        self.assertContains(response, reverse("gesto_amostra_gravar", args=[self.sinal.pk]))
        self.assertContains(response, "Espaço")
        self.assertContains(response, self.sinal.titulo)

    def test_gravar_bloqueia_sinal_estatico(self):
        estatico = Sinal.objects.create(titulo="A")
        response = self.client.get(reverse("gesto_gravar", args=[estatico.pk]))
        self.assertEqual(response.status_code, 404)

    def test_lista_de_gestos_exibe_o_tipo(self):
        response = self.client.get(reverse("gestos"))
        self.assertContains(response, "Movimento")


class GestoAmostraApagarTests(TemporalBase):
    """Exclusão de amostras pela página do sinal."""

    def test_apagar_post_redireciona_e_remove_tudo(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        caminho = Path(self.media_tmp) / amostra.arquivo_dados
        self.assertTrue(caminho.is_file())
        response = self.client.post(
            reverse("gesto_amostra_apagar", args=[self.sinal.pk, amostra.pk]),
            follow=True,
        )
        self.assertRedirects(response, reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertContains(response, "apagada")
        self.assertEqual(AmostraMovimento.objects.count(), 0)
        self.assertFalse(caminho.exists())

    def test_apagar_rejeita_get(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        response = self.client.get(
            reverse("gesto_amostra_apagar", args=[self.sinal.pk, amostra.pk])
        )
        self.assertEqual(response.status_code, 405)
        self.assertEqual(AmostraMovimento.objects.count(), 1)

    def test_apagar_amostra_de_outro_sinal_retorna_404(self):
        outro = Sinal.objects.create(titulo="Z", tipo=Sinal.Tipo.MOVIMENTO)
        amostra = salvar_amostra(outro, self.gerar_sequencia())
        response = self.client.post(
            reverse("gesto_amostra_apagar", args=[self.sinal.pk, amostra.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(AmostraMovimento.objects.count(), 1)

    def test_apagar_amostra_inexistente_retorna_404(self):
        response = self.client.post(
            reverse("gesto_amostra_apagar", args=[self.sinal.pk, 9999])
        )
        self.assertEqual(response.status_code, 404)

    def test_detalhe_exibe_botao_de_apagar(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        response = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertContains(response, "Apagar")
        self.assertContains(
            response,
            reverse("gesto_amostra_apagar", args=[self.sinal.pk, amostra.pk]),
        )


class ExcluirVariasAmostrasTests(TemporalBase):
    """Tabela do sinal: marcar uma, várias ou todas as amostras e excluir."""

    def setUp(self):
        super().setUp()
        self.amostras = [salvar_amostra(self.sinal, self.gerar_sequencia()) for _ in range(3)]
        self.outro = Sinal.objects.create(titulo="Z", tipo=Sinal.Tipo.MOVIMENTO)
        self.do_outro = salvar_amostra(self.outro, self.gerar_sequencia())

    def apagar(self, ids, sinal=None):
        url = reverse("gesto_amostras_apagar", args=[(sinal or self.sinal).pk])
        return self.client.post(url, {"amostra": ids}, follow=True)

    def test_tabela_tem_selecao(self):
        resposta = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertContains(resposta, 'id="selecionar-todas"')
        self.assertContains(resposta, 'form="form-apagar" name="amostra"', count=3)
        self.assertContains(resposta, "js/selecao-amostras.js")

    def test_apaga_as_marcadas_com_os_arquivos(self):
        caminho = Path(self.media_tmp) / self.amostras[0].arquivo_dados
        self.assertTrue(caminho.exists())
        resposta = self.apagar([self.amostras[0].pk, self.amostras[2].pk])
        self.assertContains(resposta, "2 amostras apagadas")
        self.assertEqual(
            list(AmostraMovimento.objects.filter(sinal=self.sinal).values_list("pk", flat=True)),
            [self.amostras[1].pk],
        )
        self.assertFalse(caminho.exists())

    def test_ids_de_outro_sinal_sao_ignorados(self):
        resposta = self.apagar([self.do_outro.pk, "abc"])
        self.assertContains(resposta, "Nenhuma amostra selecionada")
        self.assertTrue(AmostraMovimento.objects.filter(pk=self.do_outro.pk).exists())
        self.assertEqual(AmostraMovimento.objects.filter(sinal=self.sinal).count(), 3)

    def test_todas_de_uma_vez(self):
        self.assertContains(self.apagar([a.pk for a in self.amostras]), "3 amostras apagadas")
        self.assertFalse(AmostraMovimento.objects.filter(sinal=self.sinal).exists())
        self.assertTrue(AmostraMovimento.objects.filter(pk=self.do_outro.pk).exists())

    def test_so_admin_e_so_post(self):
        url = reverse("gesto_amostras_apagar", args=[self.sinal.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(url, {"amostra": [self.amostras[0].pk]}).status_code, 302)
        self.assertEqual(AmostraMovimento.objects.filter(sinal=self.sinal).count(), 3)
