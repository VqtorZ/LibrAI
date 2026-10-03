"""Testes do LibrAI: model, form, views de gestos, admin e rotas existentes,
além da coleta temporal de movimentos (amostras, validação e persistência).

Observação: /video/ não é testado aqui porque abre a webcam (hardware),
o que torna o teste dependente de máquina — ele é validado
funcionalmente com o servidor em execução.
"""
import base64
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import SinalForm
from .models import AmostraMovimento, Sinal
from .movimentos import (
    DURACAO_MAX_MS,
    FRAMES_MIN_VALIDOS,
    AmostraInvalida,
    salvar_amostra,
    ler_sequencia,
    validar_payload,
)


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


class SinalTipoTests(TestCase):
    """O sinal agora nasce com um tipo: estático (default) ou movimento."""

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


class TemporalBase(TestCase):
    """Isolamento do MEDIA_ROOT para os testes da coleta temporal."""

    @classmethod
    def setUpTestData(cls):
        cls.sinal = Sinal.objects.create(
            titulo="J", tipo=Sinal.Tipo.MOVIMENTO, descricao="Letra J"
        )

    def setUp(self):
        self.media_tmp = tempfile.mkdtemp()
        ajuste = override_settings(MEDIA_ROOT=self.media_tmp)
        ajuste.enable()
        self.addCleanup(ajuste.disable)
        self.addCleanup(shutil.rmtree, self.media_tmp, ignore_errors=True)

    @staticmethod
    def gerar_sequencia(total=15, nulos=0, intervalo_ms=66):
        """Sequência sintética: 63 valores por frame, com 'nulos' frames sem mão."""
        sequencia = []
        for i in range(total):
            valido = i >= nulos
            sequencia.append({
                "timestamp_ms": i * intervalo_ms,
                "landmarks": [float(i % 10)] * 63 if valido else None,
            })
        return sequencia

    @staticmethod
    def gerar_payload(total=15, intervalo_ms=66):
        """Payload no formato enviado pela página de gravação."""
        return {
            "frames": [
                {
                    "timestamp_ms": i * intervalo_ms,
                    "imagem": base64.b64encode(b"frame-falso").decode(),
                }
                for i in range(total)
            ]
        }


class AmostraMovimentoTests(TemporalBase):
    """Serviço de amostras: validação, persistência fora do banco e leitura."""

    def test_salvar_cria_registro_e_arquivo_json(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(15))
        self.assertEqual(AmostraMovimento.objects.count(), 1)
        self.assertEqual(amostra.sinal, self.sinal)
        self.assertEqual(
            amostra.arquivo_dados, f"movimentos/{self.sinal.pk}/{amostra.pk}.json"
        )
        self.assertTrue(Path(self.media_tmp).joinpath(amostra.arquivo_dados).is_file())

    def test_conteudo_do_arquivo_e_versionado_e_completo(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=16, nulos=3))
        conteudo = ler_sequencia(amostra)
        self.assertEqual(conteudo["version"], 1)
        self.assertEqual(conteudo["sinal_id"], self.sinal.pk)
        self.assertEqual(conteudo["quantidade_frames"], 16)
        self.assertEqual(conteudo["quantidade_frames_validos"], 13)
        self.assertEqual(conteudo["quantidade_landmarks"], 21)
        self.assertEqual(len(conteudo["frames"]), 16)
        self.assertEqual(conteudo["frames"][0]["landmarks"], None)
        self.assertEqual(len(conteudo["frames"][3]["landmarks"]), 63)
        self.assertEqual(conteudo["frames"][5]["timestamp_ms"], 5 * 66)

    def test_frames_sem_mao_nao_sao_descartados(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15, nulos=4))
        conteudo = ler_sequencia(amostra)
        self.assertEqual(amostra.quantidade_frames, 15)
        self.assertEqual(
            sum(1 for f in conteudo["frames"] if f["landmarks"] is None), 4
        )

    def test_dados_tecnicos_calculados(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=16, intervalo_ms=66))
        self.assertEqual(amostra.duracao_ms, 15 * 66)
        self.assertEqual(amostra.quantidade_frames, 16)
        self.assertEqual(amostra.quantidade_landmarks, 21)
        self.assertEqual(amostra.versao_features, 1)
        self.assertEqual(amostra.fps, round(15 / (15 * 66 / 1000), 1))
        self.assertEqual(amostra.duracao_segundos, 1.0)

    def test_rejeita_amostra_com_poucos_frames_validos(self):
        with self.assertRaises(AmostraInvalida):
            salvar_amostra(self.sinal, self.gerar_sequencia(total=15, nulos=6))
        self.assertEqual(AmostraMovimento.objects.count(), 0)

    def test_aceita_exatamente_o_minimo_de_frames_validos(self):
        amostra = salvar_amostra(
            self.sinal, self.gerar_sequencia(total=FRAMES_MIN_VALIDOS)
        )
        self.assertEqual(amostra.quantidade_frames, FRAMES_MIN_VALIDOS)

    def test_leitura_rejeita_caminho_fora_do_media(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        amostra.arquivo_dados = "movimentos/../../app/settings.py"
        with self.assertRaises(AmostraInvalida):
            ler_sequencia(amostra)

    def test_leitura_rejeita_arquivo_ausente(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        amostra.arquivo_dados = f"movimentos/{self.sinal.pk}/999999.json"
        with self.assertRaises(AmostraInvalida):
            ler_sequencia(amostra)

    def test_multiplas_amostras_para_o_mesmo_sinal(self):
        for _ in range(3):
            salvar_amostra(self.sinal, self.gerar_sequencia())
        self.assertEqual(self.sinal.amostras.count(), 3)


class ValidarPayloadTests(TestCase):
    """Validação do que chega da gravação antes de qualquer processamento."""

    @staticmethod
    def payload(timestamps):
        return {
            "frames": [
                {"timestamp_ms": ts, "imagem": base64.b64encode(b"x").decode()}
                for ts in timestamps
            ]
        }

    def test_aceita_payload_valido(self):
        frames = validar_payload(self.payload([0, 66, 132]))
        self.assertEqual([ts for ts, _ in frames], [0, 66, 132])

    def test_rejeita_sem_frames(self):
        with self.assertRaises(AmostraInvalida):
            validar_payload({"frames": []})

    def test_rejeita_acima_da_duracao_maxima(self):
        with self.assertRaises(AmostraInvalida):
            validar_payload(self.payload([0, DURACAO_MAX_MS + 1]))

    def test_rejeita_timestamp_invalido(self):
        dados = self.payload([0, 66])
        dados["frames"][1]["timestamp_ms"] = "setenta"
        with self.assertRaises(AmostraInvalida):
            validar_payload(dados)

    def test_rejeita_base64_corrompido(self):
        dados = self.payload([0, 66])
        dados["frames"][0]["imagem"] = "###não é base64###"
        with self.assertRaises(AmostraInvalida):
            validar_payload(dados)

    def test_rejeita_timestamps_fora_de_ordem(self):
        with self.assertRaises(AmostraInvalida):
            validar_payload(self.payload([100, 0]))

    def test_rejeita_estrutura_inesperada(self):
        with self.assertRaises(AmostraInvalida):
            validar_payload(["frame"])


class GestoDetalheEGravarTests(TemporalBase):
    """Rotas novas: detalhe do sinal e estúdio de gravação."""

    def test_detalhe_exibe_sinal(self):
        response = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.sinal.titulo)
        self.assertContains(response, "Gravar nova amostra")
        self.assertContains(response, "Ainda não há amostras gravadas")

    def test_detalhe_lista_amostras(self):
        AmostraMovimento.objects.create(
            sinal=self.sinal, quantidade_frames=42, duracao_ms=2800,
            arquivo_dados="movimentos/1/1.json", fps=15.0,
        )
        response = self.client.get(reverse("gesto_detalhe", args=[self.sinal.pk]))
        self.assertContains(response, "1 amostra")
        self.assertContains(response, "Amostra #")

    def test_detalhe_de_sinal_inexistente_retorna_404(self):
        response = self.client.get(reverse("gesto_detalhe", args=[9999]))
        self.assertEqual(response.status_code, 404)

    def test_gravar_abre_para_sinal_de_movimento(self):
        response = self.client.get(reverse("gesto_gravar", args=[self.sinal.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="preview"')
        self.assertContains(response, self.sinal.titulo)

    def test_gravar_bloqueia_sinal_estatico(self):
        estatico = Sinal.objects.create(titulo="A")
        response = self.client.get(reverse("gesto_gravar", args=[estatico.pk]))
        self.assertEqual(response.status_code, 404)

    def test_lista_de_gestos_exibe_o_tipo(self):
        response = self.client.get(reverse("gestos"))
        self.assertContains(response, "Movimento")


class GestoAmostraSalvarTests(TemporalBase):
    """Endpoint de salvamento: validação, segurança e integração da pipeline."""

    def test_rejeita_get(self):
        response = self.client.get(
            reverse("gesto_amostra_salvar", args=[self.sinal.pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_rejeita_json_invalido(self):
        response = self.client.post(
            reverse("gesto_amostra_salvar", args=[self.sinal.pk]),
            data="{isto não é json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("JSON inválido", response.json()["erro"])

    def test_rejeita_payload_vazio(self):
        response = self.client.post(
            reverse("gesto_amostra_salvar", args=[self.sinal.pk]),
            data=json.dumps({"frames": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Nenhum frame", response.json()["erro"])

    def test_rejeita_sinal_estatico(self):
        estatico = Sinal.objects.create(titulo="A")
        response = self.client.post(
            reverse("gesto_amostra_salvar", args=[estatico.pk]),
            data=json.dumps(self.gerar_payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_rejeita_sinal_inexistente(self):
        response = self.client.post(
            reverse("gesto_amostra_salvar", args=[9999]),
            data=json.dumps(self.gerar_payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_rejeita_amostra_sem_maos_detectadas(self):
        """Pipeline real: imagens falsas não decodificam, logo não há mão alguma."""
        response = self.client.post(
            reverse("gesto_amostra_salvar", args=[self.sinal.pk]),
            data=json.dumps(self.gerar_payload(total=12)),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("frames com a mão", response.json()["erro"])
        self.assertEqual(AmostraMovimento.objects.count(), 0)

    def test_salva_amostra_valida_de_ponta_a_ponta(self):
        sequencia_falsa = self.gerar_sequencia(total=15)
        with patch("libras.views.extrair_landmarks", return_value=sequencia_falsa):
            response = self.client.post(
                reverse("gesto_amostra_salvar", args=[self.sinal.pk]),
                data=json.dumps(self.gerar_payload(total=15)),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["quantidade_frames"], 15)
        amostra = AmostraMovimento.objects.get(pk=payload["amostra_id"])
        self.assertEqual(amostra.sinal, self.sinal)
        self.assertIsNotNone(amostra.arquivo_dados)
        conteudo = ler_sequencia(amostra)
        self.assertEqual(conteudo["sinal_id"], self.sinal.pk)
