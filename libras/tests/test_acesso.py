"""Login e controle de acesso: Gestos só para administradores."""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
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

    def setUp(self):
        cache.clear()  # contadores de tentativas de login

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

    def test_bloqueia_depois_de_5_erros_no_mesmo_email(self):
        for _ in range(5):
            self.assertContains(self.entrar("ana@exemplo.com", "errada"), "E-mail ou senha incorretos")
        # Bloqueado: nem a senha certa entra (e não dá pista se estaria certa).
        response = self.entrar("ANA@exemplo.com", "senha-forte-1")
        self.assertContains(response, "Muitas tentativas erradas")
        self.assertEqual(self.client.get(reverse("gestos")).status_code, 302)
        # Outra conta continua entrando normalmente.
        User.objects.create_user("bia@exemplo.com", "bia@exemplo.com", "senha-forte-3", is_staff=True)
        self.assertRedirects(self.entrar("bia@exemplo.com", "senha-forte-3"), reverse("gestos"))

    def test_acertar_zera_os_erros(self):
        for _ in range(4):
            self.entrar("ana@exemplo.com", "errada")
        self.assertRedirects(self.entrar("ana@exemplo.com", "senha-forte-1"), reverse("gestos"))
        self.client.post(reverse("sair"))
        for _ in range(4):
            self.assertContains(self.entrar("ana@exemplo.com", "errada"), "E-mail ou senha incorretos")

    @override_settings(LOGIN_TENTATIVAS_POR_IP=3, LOGIN_IP_DO_CABECALHO="HTTP_X_REAL_IP")
    def test_bloqueia_por_ip_usando_o_cabecalho_do_servidor(self):
        for indice in range(3):
            self.client.post(
                reverse("entrar"), {"username": f"tentativa{indice}@exemplo.com", "password": "errada"},
                HTTP_X_REAL_IP="203.0.113.7",
            )
        bloqueado = self.client.post(
            reverse("entrar"), {"username": "ana@exemplo.com", "password": "senha-forte-1"},
            HTTP_X_REAL_IP="203.0.113.7",
        )
        self.assertContains(bloqueado, "Muitas tentativas erradas")
        # Outro IP (outra pessoa) não é afetado.
        liberado = self.client.post(
            reverse("entrar"), {"username": "ana@exemplo.com", "password": "senha-forte-1"},
            HTTP_X_REAL_IP="198.51.100.2",
        )
        self.assertRedirects(liberado, reverse("gestos"))

    def test_tela_de_login(self):
        response = self.client.get(reverse("entrar"))
        self.assertContains(response, "Área dos administradores")
        self.assertContains(response, 'type="email"')
        self.assertContains(response, 'id="mostrar-senha"')
        self.assertContains(response, "css/entrar.css?v=")


@RAPIDO
class CriarAdminTests(TestCase):
    def criar(self, *args, senhas=("libras-segredo-123", "libras-segredo-123")):
        with patch("libras.management.commands.criar_admin.getpass.getpass", side_effect=list(senhas)):
            call_command("criar_admin", *args, stdout=StringIO())

    def test_cria_administrador(self):
        self.criar("Bia@Exemplo.com", "--nome", "Bia")
        usuario = User.objects.get(username="bia@exemplo.com")
        self.assertTrue(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertEqual(usuario.first_name, "Bia")
        self.assertTrue(usuario.check_password("libras-segredo-123"))

    def test_cria_master_e_atualiza_conta_existente(self):
        self.criar("bia@exemplo.com")
        self.criar("bia@exemplo.com", "--master", senhas=("outra-senha-456", "outra-senha-456"))
        usuario = User.objects.get(username="bia@exemplo.com")
        self.assertTrue(usuario.is_superuser)
        self.assertTrue(usuario.check_password("outra-senha-456"))
        self.assertEqual(User.objects.count(), 1)

    def test_senhas_diferentes(self):
        with self.assertRaises(CommandError):
            self.criar("bia@exemplo.com", senhas=("um", "dois"))
        self.assertFalse(User.objects.exists())

    def test_senha_fraca_e_recusada(self):
        for fraca in ("curta-1", "1234567890123", "password123"):
            with self.subTest(fraca=fraca):
                with self.assertRaises(CommandError) as contexto:
                    self.criar("bia@exemplo.com", senhas=(fraca, fraca))
                self.assertIn("Senha fraca", str(contexto.exception))
        self.assertFalse(User.objects.exists())

    def test_email_invalido(self):
        with self.assertRaises(CommandError):
            self.criar("giovana,gii@gmail.com")


class LoginDoAdminTests(TestCase):
    def test_login_do_admin_passa_pela_tela_do_site(self):
        # A tela do site tem o limite de tentativas; a do /admin/ não teria.
        resposta = self.client.get("/admin/login/?next=/admin/")
        self.assertRedirects(resposta, reverse("entrar") + "?next=/admin/", fetch_redirect_response=False)


@RAPIDO
class TrocarSenhaTests(TestCase):
    URL = "/conta/senha/"

    def setUp(self):
        cache.clear()
        self.usuario = User.objects.create_user(
            "ana@exemplo.com", "ana@exemplo.com", "senha-antiga-1", first_name="Ana", is_staff=True
        )
        self.client.force_login(self.usuario)

    def trocar(self, atual, nova, repetida=None):
        return self.client.post(reverse("trocar_senha"), {
            "old_password": atual, "new_password1": nova, "new_password2": repetida or nova,
        })

    def test_pagina(self):
        self.assertEqual(reverse("trocar_senha"), self.URL)
        resposta = self.client.get(self.URL)
        self.assertContains(resposta, "Trocar minha senha")
        self.assertContains(resposta, "ana@exemplo.com")
        self.assertContains(resposta, "Senha atual")
        self.assertContains(resposta, 'id="mostrar-senhas"')
        # O "Olá, Ana" do cabeçalho leva até aqui.
        self.assertContains(self.client.get(reverse("inicio")), f'href="{self.URL}"')

    def test_troca_e_continua_logado(self):
        resposta = self.trocar("senha-antiga-1", "libras-mao-azul-2026")
        self.assertRedirects(resposta, reverse("gestos"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("gestos")), "Senha trocada")
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("libras-mao-azul-2026"))

    def test_senha_atual_errada(self):
        resposta = self.trocar("chute-errado", "libras-mao-azul-2026")
        self.assertContains(resposta, "A senha atual não confere")
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("senha-antiga-1"))

    def test_regras_da_senha_nova(self):
        casos = [
            ("curta-1", "curta-1", None),
            ("1234567890123", "1234567890123", None),
            ("libras-mao-azul-2026", "libras-mao-azul-2027", "não são iguais"),
            ("senha-antiga-1", "senha-antiga-1", "diferente da atual"),
        ]
        for nova, repetida, mensagem in casos:
            with self.subTest(nova=nova):
                resposta = self.trocar("senha-antiga-1", nova, repetida)
                self.assertEqual(resposta.status_code, 200)
                if mensagem:
                    self.assertContains(resposta, mensagem)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("senha-antiga-1"))

    def test_visitante_vai_para_o_login(self):
        self.client.logout()
        self.assertRedirects(
            self.client.get(self.URL), f"{reverse('entrar')}?next={self.URL}", fetch_redirect_response=False
        )
