"""Testes do LibrAI: model, form, views de gestos, admin e rotas existentes.

Observação: /video/ não é testado aqui porque abre a webcam (hardware),
o que torna o teste dependente de máquina — ele é validado
funcionalmente com o servidor em execução.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import SinalForm
from .models import Sinal


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
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LibrAI")

    def test_recognizer(self):
        response = self.client.get(reverse("recognizer"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="label"')

    def test_status(self):
        response = self.client.get(reverse("status"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("label", payload)
        self.assertIn("error", payload)
        self.assertIn("model_ready", payload)
        self.assertTrue(payload["model_ready"])
