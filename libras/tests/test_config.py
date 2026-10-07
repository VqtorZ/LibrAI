"""Configuração por ambiente: .env, modo produção e check --deploy."""
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from config.ambiente import carregar_env, ligado, lista


class AmbienteTests(SimpleTestCase):
    def setUp(self):
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        self.arquivo = pasta / ".env"

    def test_le_o_arquivo_sem_sobrescrever_o_sistema(self):
        self.arquivo.write_text(
            "﻿# comentário\n\nTESTE_A=1\nTESTE_B = 'com espaço'\nTESTE_C=\"x=y\"\nlinha sem igual\nTESTE_D=arquivo\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"TESTE_D": "sistema"}):
            carregar_env(self.arquivo)
            self.assertEqual(os.environ["TESTE_A"], "1")
            self.assertEqual(os.environ["TESTE_B"], "com espaço")
            self.assertEqual(os.environ["TESTE_C"], "x=y")
            self.assertEqual(os.environ["TESTE_D"], "sistema")
            for chave in ("TESTE_A", "TESTE_B", "TESTE_C"):
                del os.environ[chave]

    def test_arquivo_ausente_nao_faz_nada(self):
        carregar_env(self.arquivo)

    def test_ligado_e_lista(self):
        with patch.dict(os.environ, {"X1": "Sim", "X2": "0", "X3": " a.com, ,b.com "}):
            self.assertTrue(ligado("X1"))
            self.assertFalse(ligado("X2"))
            self.assertTrue(ligado("NAO_EXISTE", padrao=True))
            self.assertEqual(lista("X3"), ["a.com", "b.com"])
            self.assertEqual(lista("NAO_EXISTE"), [])

    def test_local_continua_em_desenvolvimento(self):
        # (DEBUG não serve de prova: o executor de testes sempre o desliga.)
        self.assertFalse(settings.PRODUCAO)
        self.assertEqual(settings.SECRET_KEY, settings.CHAVE_DE_DESENVOLVIMENTO)
        self.assertFalse(settings.SESSION_COOKIE_SECURE)
        self.assertIn("127.0.0.1", settings.ALLOWED_HOSTS)


class ProducaoTests(SimpleTestCase):
    """Sobe o Django num processo à parte, com as variáveis do servidor."""

    def rodar(self, *argumentos, **variaveis):
        ambiente = {k: v for k, v in os.environ.items() if not k.startswith("LIBRAI_")}
        ambiente.update(variaveis)
        return subprocess.run(
            [sys.executable, "manage.py", *argumentos],
            cwd=settings.BASE_DIR, env=ambiente, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )

    def test_check_deploy_sem_avisos(self):
        resultado = self.rodar(
            "check", "--deploy", "--fail-level", "WARNING",
            LIBRAI_PRODUCAO="1", LIBRAI_SECRET_KEY=secrets.token_urlsafe(50),
            LIBRAI_HOSTS="exemplo.pythonanywhere.com",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_configuracoes_de_producao(self):
        resultado = self.rodar(
            "shell", "-c",
            "from django.conf import settings as s; print(s.DEBUG, s.CSRF_TRUSTED_ORIGINS, "
            "s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.LOGIN_IP_DO_CABECALHO)",
            LIBRAI_PRODUCAO="1", LIBRAI_SECRET_KEY=secrets.token_urlsafe(50),
            LIBRAI_HOSTS="exemplo.pythonanywhere.com",
        )
        self.assertEqual(
            resultado.stdout.strip().splitlines()[-1],
            "False ['https://exemplo.pythonanywhere.com'] True True HTTP_X_REAL_IP",
            resultado.stderr,
        )

    def test_producao_sem_chave_ou_sem_host_nao_sobe(self):
        sem_chave = self.rodar("check", LIBRAI_PRODUCAO="1", LIBRAI_HOSTS="exemplo.pythonanywhere.com")
        self.assertNotEqual(sem_chave.returncode, 0)
        self.assertIn("LIBRAI_SECRET_KEY", sem_chave.stderr)
        sem_host = self.rodar("check", LIBRAI_PRODUCAO="1", LIBRAI_SECRET_KEY=secrets.token_urlsafe(50))
        self.assertNotEqual(sem_host.returncode, 0)
        self.assertIn("LIBRAI_HOSTS", sem_host.stderr)


class BackupDadosTests(SimpleTestCase):
    def test_gera_zip_com_banco_amostras_e_modelos(self):
        import sqlite3
        import zipfile
        from io import StringIO

        from django.core.management import call_command

        from libras import caminhos
        from libras.management.commands import backup_dados

        raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        dados = raiz / "dados"
        (dados / "amostras_estaticas").mkdir(parents=True)
        (dados / "amostras_estaticas" / "alfabeto.csv").write_text("label\nA\n", encoding="utf-8")
        (dados / "amostras_movimento" / "2-j").mkdir(parents=True)
        (dados / "amostras_movimento" / "2-j" / "7.json").write_text("{}", encoding="utf-8")
        (dados / "modelos_treinados").mkdir()
        (dados / "modelos_treinados" / "alfabeto.joblib").write_bytes(b"modelo")
        (dados / "modelos_treinados" / "x.joblib.tmp").write_bytes(b"meio-salvo")
        banco = dados / "banco.sqlite3"
        conexao = sqlite3.connect(banco)
        conexao.execute("create table t (x)")
        conexao.execute("insert into t values (42)")
        conexao.commit()
        conexao.close()
        pastas = (dados / "amostras_estaticas", dados / "amostras_movimento", dados / "modelos_treinados")
        with patch.object(caminhos, "RAIZ", raiz), patch.object(caminhos, "BANCO", banco), \
                patch.object(backup_dados, "PASTAS", pastas):
            saida = StringIO()
            call_command("backup_dados", stdout=saida)
        self.assertIn("4 arquivos", saida.getvalue())  # o .tmp fica de fora
        (arquivo,) = (raiz / "backups").glob("librai-*.zip")
        with zipfile.ZipFile(arquivo) as zip_:
            nomes = sorted(zip_.namelist())
            self.assertEqual(nomes, [
                "dados/amostras_estaticas/alfabeto.csv",
                "dados/amostras_movimento/2-j/7.json",
                "dados/banco.sqlite3",
                "dados/modelos_treinados/alfabeto.joblib",
            ])
            zip_.extract("dados/banco.sqlite3", raiz / "restaurado")
        conexao = sqlite3.connect(raiz / "restaurado" / "dados" / "banco.sqlite3")
        self.assertEqual(conexao.execute("select x from t").fetchone(), (42,))
        conexao.close()


class PublicarTests(SimpleTestCase):
    """Site no ar a partir deste computador (publicar.cmd)."""

    def test_le_o_link_do_tunel(self):
        from libras.management.commands.publicar import link_na_linha

        linha = "2026-10-07T06:40:01Z INF |  https://ab-cd-12.trycloudflare.com                |"
        self.assertEqual(link_na_linha(linha), "https://ab-cd-12.trycloudflare.com")
        self.assertIsNone(link_na_linha("INF Requesting new quick Tunnel on trycloudflare.com..."))

    def test_detecta_porta_ocupada(self):
        import socket

        from libras.management.commands.publicar import porta_ocupada

        with socket.socket() as servidor:
            servidor.bind(("127.0.0.1", 0))
            servidor.listen()
            porta = servidor.getsockname()[1]
            self.assertTrue(porta_ocupada(porta))
        self.assertFalse(porta_ocupada(porta))

    def test_recusa_fora_do_modo_producao(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as contexto:
            call_command("publicar", "--sem-tunel")
        self.assertIn("publicar.cmd", str(contexto.exception))

    def test_env_publico_aceita_o_link_do_tunel(self):
        import secrets
        import subprocess
        import sys

        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        arquivo = pasta / ".env.teste"
        arquivo.write_text(
            "LIBRAI_PRODUCAO=1\n"
            f"LIBRAI_SECRET_KEY={secrets.token_urlsafe(50)}\n"
            "LIBRAI_HOSTS=.trycloudflare.com,127.0.0.1\n"
            "LIBRAI_IP_CABECALHO=HTTP_CF_CONNECTING_IP\n",
            encoding="utf-8",
        )
        ambiente = {k: v for k, v in os.environ.items() if not k.startswith("LIBRAI_")}
        ambiente["LIBRAI_ENV"] = str(arquivo)
        codigo = (
            "from django.conf import settings as s; from django.test import Client; "
            "c = Client(HTTP_HOST='abc-def.trycloudflare.com', HTTP_X_FORWARDED_PROTO='https'); "
            "r = c.get('/'); "
            "print(s.PRODUCAO, s.CSRF_TRUSTED_ORIGINS, s.LOGIN_IP_DO_CABECALHO, r.status_code)"
        )
        resultado = subprocess.run(
            [sys.executable, "manage.py", "shell", "-c", codigo], cwd=settings.BASE_DIR, env=ambiente,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(
            resultado.stdout.strip().splitlines()[-1],
            "True ['https://*.trycloudflare.com', 'https://127.0.0.1'] HTTP_CF_CONNECTING_IP 200",
            resultado.stderr,
        )


class DesligarTests(SimpleTestCase):
    NETSTAT = (
        "  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1588\n"
        "  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       4242\n"
        "  TCP    127.0.0.1:50649        127.0.0.1:8080         TIME_WAIT       0\n"
    )

    def test_acha_o_servidor_pela_porta(self):
        from libras.management.commands.desligar import pid_na_porta, tunel_da_porta

        self.assertEqual(pid_na_porta(self.NETSTAT, 8080), 4242)
        self.assertIsNone(pid_na_porta(self.NETSTAT, 8090))
        self.assertTrue(tunel_da_porta('"cloudflared.exe" tunnel --url http://127.0.0.1:8080', 8080))
        self.assertFalse(tunel_da_porta('"cloudflared.exe" tunnel --url http://127.0.0.1:8090', 8080))

    def test_nunca_encerra_outro_programa(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        from libras.management.commands import desligar

        resultado = type("R", (), {"stdout": self.NETSTAT})()
        with patch.object(desligar.subprocess, "run", return_value=resultado) as rodar, \
                patch.object(desligar, "processos", return_value={4242: ("chrome.exe", "chrome.exe --x")}):
            with self.assertRaises(CommandError) as contexto:
                call_command("desligar")
        self.assertIn("outro programa", str(contexto.exception))
        comandos = [chamada.args[0][0] for chamada in rodar.call_args_list]
        self.assertNotIn("taskkill", comandos)
