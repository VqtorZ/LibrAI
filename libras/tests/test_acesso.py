"""Login e controle de acesso: Gestos só para administradores."""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from libras.models import Sinal

# Criptografia rápida só nos testes (a de produção é lenta de propósito).
RAPIDO = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@RAPIDO
class AcessoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sinal = Sinal.objects.create(titulo="J", tipo=Sinal.Tipo.MOVIMENTO)
        cls.admin = User.objects.create_user(
            "ana@exemplo.com", "ana@exemplo.com", "senha-forte-1", first_name="Ana", is_staff=True
        )
        cls.comum = User.objects.create_user("leo@exemplo.com", "leo@exemplo.com", "senha-forte-2")

    def entrar(self, email, senha, **extra):
        return self.client.post(reverse("entrar"), {"username": email, "password": senha, **extra})

    # ------------------------------------------------------------ visitante
    def test_paginas_publicas_abrem_sem_login(self):
        for nome in ("inicio", "reconhecer", "entrar"):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)
        # O reconhecimento ao vivo também é público.
        resposta = self.client.post(
            reverse("api_quadros"),
            {"canal": "visitante-123", "quadros": [{"t": 0, "marcos": None}]},
            content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 200)

    def test_area_de_gestos_pede_login(self):
        for url in (
            reverse("gestos"),
            reverse("gesto_novo"),
            reverse("gesto_detalhe", args=[self.sinal.pk]),
            reverse("gesto_gravar", args=[self.sinal.pk]),
            reverse("gesto_excluir", args=[self.sinal.pk]),
            reverse("alfabeto_gravar"),
        ):
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('entrar')}?next={url}", fetch_redirect_response=False)

    def test_visitante_nao_altera_nada(self):
        for url in (
            reverse("gesto_excluir", args=[self.sinal.pk]),
            reverse("treinar_movimentos"),
            reverse("treinar_alfabeto"),
            reverse("alfabeto_amostra_salvar"),
            reverse("alfabeto_amostra_desfazer"),
            reverse("gesto_amostra_gravar", args=[self.sinal.pk]),
        ):
            self.assertEqual(self.client.post(url).status_code, 302, url)
        self.assertTrue(Sinal.objects.filter(pk=self.sinal.pk).exists())

    # ---------------------------------------------------------------- login
    def test_entra_pelo_email_sem_diferenciar_maiusculas(self):
        response = self.entrar("ANA@Exemplo.com", "senha-forte-1")
        self.assertRedirects(response, reverse("gestos"))
        self.assertEqual(self.client.get(reverse("gestos")).status_code, 200)

    def test_volta_para_a_pagina_pedida(self):
        destino = reverse("alfabeto_gravar")
        response = self.entrar("ana@exemplo.com", "senha-forte-1", next=destino)
        self.assertRedirects(response, destino, fetch_redirect_response=False)

    def test_senha_errada(self):
        response = self.entrar("ana@exemplo.com", "errada")
        self.assertContains(response, "E-mail ou senha incorretos")
        self.assertEqual(self.client.get(reverse("gestos")).status_code, 302)

    def test_conta_sem_acesso_de_administrador(self):
        response = self.entrar("leo@exemplo.com", "senha-forte-2")
        self.assertContains(response, "não tem acesso de administrador")
        # Mesmo logada por outro meio, a conta comum não abre Gestos.
        self.client.force_login(self.comum)
        self.assertEqual(self.client.get(reverse("gestos")).status_code, 302)

    def test_cabecalho_mostra_entrar_ou_ola_e_sair(self):
        response = self.client.get(reverse("inicio"))
        self.assertContains(response, f'href="{reverse("entrar")}"')
        self.assertNotContains(response, "Olá,")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("inicio"))
        self.assertContains(response, "Olá, Ana")
        self.assertContains(response, f'action="{reverse("sair")}"')

    def test_sair(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("sair"))
        self.assertRedirects(response, reverse("inicio"))
        self.assertEqual(self.client.get(reverse("gestos")).status_code, 302)

    def test_ja_logado_nao_ve_o_formulario(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("entrar")), reverse("gestos"))

    def test_tela_de_login(self):
        response = self.client.get(reverse("entrar"))
        self.assertContains(response, "Área dos administradores")
        self.assertContains(response, 'type="email"')
        self.assertContains(response, 'id="mostrar-senha"')
        self.assertContains(response, "css/entrar.css?v=")


@RAPIDO
class CriarAdminTests(TestCase):
    def criar(self, *args, senhas=("segredo-123", "segredo-123")):
        with patch("libras.management.commands.criar_admin.getpass.getpass", side_effect=list(senhas)):
            call_command("criar_admin", *args, stdout=StringIO())

    def test_cria_administrador(self):
        self.criar("Bia@Exemplo.com", "--nome", "Bia")
        usuario = User.objects.get(username="bia@exemplo.com")
        self.assertTrue(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertEqual(usuario.first_name, "Bia")
        self.assertTrue(usuario.check_password("segredo-123"))

    def test_cria_master_e_atualiza_conta_existente(self):
        self.criar("bia@exemplo.com")
        self.criar("bia@exemplo.com", "--master", senhas=("nova-456", "nova-456"))
        usuario = User.objects.get(username="bia@exemplo.com")
        self.assertTrue(usuario.is_superuser)
        self.assertTrue(usuario.check_password("nova-456"))
        self.assertEqual(User.objects.count(), 1)

    def test_senhas_diferentes(self):
        with self.assertRaises(CommandError):
            self.criar("bia@exemplo.com", senhas=("um", "dois"))
        self.assertFalse(User.objects.exists())

    def test_email_invalido(self):
        with self.assertRaises(CommandError):
            self.criar("giovana,gii@gmail.com")
