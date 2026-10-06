"""Testes do LibrAI: model, form, views de gestos, admin e rotas existentes,
além da coleta temporal de movimentos (amostras, validação e persistência).

Observação: /video/ não é testado aqui porque abre a webcam (hardware),
o que torna o teste dependente de máquina — ele é validado
funcionalmente com o servidor em execução.
"""
import base64
import json
import math
import random
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from . import temporal
from .forms import SinalForm
from .models import AmostraMovimento, Sinal
from .movimentos import (
    DURACAO_MAX_MS,
    FORMATO_VERSAO,
    FRAMES_MIN_VALIDOS,
    AmostraInvalida,
    _lateralidade,
    apagar_amostra,
    salvar_amostra,
    ler_sequencia,
    validar_payload,
)
from .ao_vivo import DetectorMovimento
from .temporal import distancia_dtw, normalizar_frame, prever, processar_frames
from .verificacao import (
    resumir,
    verificar_amostra,
    verificar_conteudo,
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
        self.assertEqual(conteudo["version"], FORMATO_VERSAO)
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
        self.assertEqual(amostra.versao_features, FORMATO_VERSAO)
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

    def test_apagar_amostra_remove_registro_e_arquivo(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        caminho = Path(self.media_tmp) / amostra.arquivo_dados
        self.assertTrue(caminho.is_file())
        apagar_amostra(amostra)
        self.assertEqual(AmostraMovimento.objects.count(), 0)
        self.assertFalse(caminho.exists())

    def test_apagar_e_tolerante_a_arquivo_ausente(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        (Path(self.media_tmp) / amostra.arquivo_dados).unlink()
        apagar_amostra(amostra)
        self.assertEqual(AmostraMovimento.objects.count(), 0)


class LateralidadeTests(TestCase):
    """Leitura da mão (direita/esquerda) informada pelo MediaPipe."""

    @staticmethod
    def resultado(rotulo):
        classificacao = type("C", (), {"label": rotulo})()
        mao = type("H", (), {"classification": [classificacao]})()
        return type("R", (), {"multi_handedness": [mao]})()

    def test_le_rotulos_validos(self):
        self.assertEqual(_lateralidade(self.resultado("Left")), "Left")
        self.assertEqual(_lateralidade(self.resultado("Right")), "Right")

    def test_rotulo_desconhecido_ou_ausente_vira_none(self):
        self.assertIsNone(_lateralidade(self.resultado("Outra")))
        self.assertIsNone(_lateralidade(type("R", (), {"multi_handedness": []})()))
        self.assertIsNone(_lateralidade(object()))


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


class VerificadorBase(TemporalBase):
    """Base do verificador: helpers para inspecionar os JSONs de teste."""

    def ler_arquivo(self, amostra):
        caminho = Path(self.media_tmp) / amostra.arquivo_dados
        return json.loads(caminho.read_text(encoding="utf-8"))

    def escrever_arquivo(self, amostra, conteudo):
        caminho = Path(self.media_tmp) / amostra.arquivo_dados
        caminho.write_text(json.dumps(conteudo), encoding="utf-8")

    def rodar_comando(self):
        saida = StringIO()
        call_command("verificar_movimentos", stdout=saida, no_color=True)
        return saida.getvalue()


class VerificarAmostraTests(VerificadorBase):
    """verificar_amostra: estrutura, consistência e integridade dos JSONs."""

    def test_amostra_valida(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        resultado = verificar_amostra(amostra)
        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.problemas, [])
        self.assertTrue(resultado.arquivo_legivel)
        self.assertEqual(resultado.total_frames, 15)
        self.assertEqual(resultado.frames_validos, 15)
        self.assertEqual(resultado.frames_sem_landmarks, 0)
        self.assertAlmostEqual(resultado.taxa_validos, 100.0)
        self.assertEqual(resultado.duracao_ms, 14 * 66)
        self.assertEqual(resultado.fps, 15.2)

    def test_frames_com_landmarks_nulos_nao_invalidam(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15, nulos=4))
        resultado = verificar_amostra(amostra)
        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.frames_validos, 11)
        self.assertEqual(resultado.frames_sem_landmarks, 4)
        self.assertAlmostEqual(resultado.taxa_validos, 11 / 15 * 100)

    def test_arquivo_corrompido(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        caminho = Path(self.media_tmp) / amostra.arquivo_dados
        caminho.write_text("{isto não é json", encoding="utf-8")
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertFalse(resultado.arquivo_legivel)
        self.assertIn("arquivo não pode ser lido", resultado.problemas[0])

    def test_arquivo_ausente(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        (Path(self.media_tmp) / amostra.arquivo_dados).unlink()
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn("não encontrado", resultado.problemas[0])

    def test_poucos_frames_validos(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        conteudo = self.ler_arquivo(amostra)
        for frame in conteudo["frames"][:6]:
            frame["landmarks"] = None
        conteudo["quantidade_frames_validos"] = 9
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn(
            f"apenas 9 frames válidos (mínimo {FRAMES_MIN_VALIDOS})",
            resultado.problemas,
        )
        self.assertEqual(resultado.frames_validos, 9)
        self.assertEqual(resultado.frames_sem_landmarks, 6)

    def test_frame_com_menos_valores(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        conteudo = self.ler_arquivo(amostra)
        conteudo["frames"][5]["landmarks"] = [0.5] * 61
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn(
            "frame 5 possui 61 valores em vez de 63", resultado.problemas
        )
        self.assertEqual(resultado.frames_validos, 14)

    def test_valores_nao_numericos(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        conteudo = self.ler_arquivo(amostra)
        conteudo["frames"][5]["landmarks"] = ["um"] + [0.5] * 62
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn(
            "frame 5: landmarks com valores não numéricos ou não finitos",
            resultado.problemas,
        )

    def test_valores_nao_finitos(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        conteudo = self.ler_arquivo(amostra)
        conteudo["frames"][5]["landmarks"] = [float("nan")] * 63
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn(
            "frame 5: landmarks com valores não numéricos ou não finitos",
            resultado.problemas,
        )

    def test_timestamp_nao_numerico(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        conteudo = self.ler_arquivo(amostra)
        conteudo["frames"][3]["timestamp_ms"] = "agora"
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn(
            "frame 3: timestamp inválido (não numérico ou não finito)",
            resultado.problemas,
        )

    def test_timestamps_fora_de_ordem(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        conteudo = self.ler_arquivo(amostra)
        conteudo["frames"][8]["timestamp_ms"] = 66
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn("frame 8: timestamps fora de ordem", resultado.problemas)

    def test_arquivo_da_versao_1_continua_valido(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        conteudo = self.ler_arquivo(amostra)
        conteudo["version"] = 1
        self.escrever_arquivo(amostra, conteudo)
        amostra.versao_features = 1
        amostra.save()
        self.assertTrue(verificar_amostra(amostra).ok)

    def test_mao_invalida(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        conteudo = self.ler_arquivo(amostra)
        conteudo["frames"][2]["mao"] = "Meio"
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn("frame 2: mão 'Meio' inválida", resultado.problemas)

    def test_mao_valida_ou_ausente_nao_invalida(self):
        sequencia = self.gerar_sequencia()
        sequencia[0]["mao"] = "Left"
        sequencia[1]["mao"] = None
        amostra = salvar_amostra(self.sinal, sequencia)
        self.assertTrue(verificar_amostra(amostra).ok)

    def test_sinal_id_inconsistente(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        conteudo = self.ler_arquivo(amostra)
        conteudo["sinal_id"] = self.sinal.pk + 100
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn("sinal_id do arquivo", resultado.problemas[0])

    def test_versao_inesperada(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        conteudo = self.ler_arquivo(amostra)
        conteudo["version"] = FORMATO_VERSAO + 1
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn("versão do arquivo", resultado.problemas[0])

    def test_sem_frames(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        conteudo = self.ler_arquivo(amostra)
        conteudo["frames"] = []
        conteudo["quantidade_frames"] = 0
        conteudo["quantidade_frames_validos"] = 0
        conteudo["duracao_ms"] = 0
        conteudo["fps"] = 0.0
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn("nenhum frame no arquivo", resultado.problemas)

    def test_metadados_do_json_inconsistentes(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        conteudo = self.ler_arquivo(amostra)
        conteudo["quantidade_frames"] = 50
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn(
            "campo 'quantidade_frames' do arquivo (50) difere do real (15)",
            resultado.problemas,
        )

    def test_registro_do_banco_inconsistente(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        amostra.quantidade_frames = 99
        amostra.save()
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn(
            "registro no banco (quantidade_frames=99) difere do arquivo (15)",
            resultado.problemas,
        )

    def test_estrutura_sem_chaves(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia())
        conteudo = self.ler_arquivo(amostra)
        del conteudo["fps"]
        self.escrever_arquivo(amostra, conteudo)
        resultado = verificar_amostra(amostra)
        self.assertFalse(resultado.ok)
        self.assertIn(
            "estrutura incompleta: campo 'fps' ausente", resultado.problemas
        )

    def test_multiplas_amostras_sao_independentes(self):
        boa = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        ruim = salvar_amostra(self.sinal, self.gerar_sequencia(total=12))
        caminho = Path(self.media_tmp) / ruim.arquivo_dados
        caminho.write_text("não é json", encoding="utf-8")
        self.assertTrue(verificar_amostra(boa).ok)
        self.assertFalse(verificar_amostra(ruim).ok)


class ResumirResultadosTests(VerificadorBase):
    """resumir: consolidação das métricas do dataset por sinal."""

    def test_resumo_apenas_amostras_validas(self):
        primeira = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        segunda = salvar_amostra(self.sinal, self.gerar_sequencia(total=20, nulos=5))
        resumo = resumir(
            [verificar_amostra(primeira), verificar_amostra(segunda)]
        )
        self.assertEqual(resumo.amostras, 2)
        self.assertEqual(resumo.validas, 2)
        self.assertEqual(resumo.invalidas, 0)
        self.assertTrue(resumo.pronto)
        self.assertEqual(resumo.frames_totais, 35)
        self.assertEqual(resumo.frames_validos, 30)
        self.assertAlmostEqual(resumo.taxa_media, (100.0 + 75.0) / 2)
        self.assertAlmostEqual(resumo.duracao_media_s, (0.924 + 1.254) / 2)

    def test_resumo_com_amostra_invalida(self):
        boa = salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        ruim = salvar_amostra(self.sinal, self.gerar_sequencia(total=12))
        (Path(self.media_tmp) / ruim.arquivo_dados).unlink()
        resumo = resumir(
            [verificar_amostra(boa), verificar_amostra(ruim)]
        )
        self.assertEqual(resumo.amostras, 2)
        self.assertEqual(resumo.validas, 1)
        self.assertEqual(resumo.invalidas, 1)
        self.assertFalse(resumo.pronto)
        # Ilegível não tem métricas: só a boa entra nas somas/médias.
        self.assertEqual(resumo.frames_totais, 15)
        self.assertEqual(resumo.frames_validos, 15)
        self.assertAlmostEqual(resumo.duracao_media_s, 0.924)


class VerificarMovimentosCommandTests(VerificadorBase):
    """Comando verificar_movimentos: relatório completo na saída padrão."""

    def test_relatorio_de_amostra_valida(self):
        salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        texto = self.rodar_comando()
        self.assertIn(f"SINAL #{self.sinal.pk} — {self.sinal.titulo}", texto)
        self.assertIn("Amostras: 1", texto)
        self.assertIn("AMOSTRA #", texto)
        self.assertIn("Frames: 15", texto)
        self.assertIn("Frames válidos: 15", texto)
        self.assertIn("Frames sem landmarks: 0", texto)
        self.assertIn("Taxa válida: 100.00%", texto)
        self.assertIn("Duração: 924 ms (0.92 s)", texto)
        self.assertIn("FPS: 15.2", texto)
        self.assertIn("Landmarks/frame: 21", texto)
        self.assertIn("Valores/frame: 63", texto)
        self.assertIn("Status: OK", texto)
        self.assertIn("RESUMO", texto)
        self.assertIn("Status do dataset: PRONTO PARA TREINAMENTO", texto)

    def test_sem_amostras_exibe_aviso(self):
        texto = self.rodar_comando()
        self.assertIn("Nenhum sinal de movimento com amostras ativas.", texto)
        self.assertNotIn("RESUMO", texto)

    def test_relatorio_de_amostra_invalida(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(total=12))
        (Path(self.media_tmp) / amostra.arquivo_dados).unlink()
        texto = self.rodar_comando()
        self.assertIn("Status: INVÁLIDA", texto)
        self.assertIn("Problemas:", texto)
        self.assertIn("- arquivo não pode ser lido", texto)
        self.assertIn("Status do dataset: REVISAR AMOSTRAS", texto)
        self.assertNotIn("PRONTO PARA TREINAMENTO", texto)

    def test_multiplas_amostras_no_resumo(self):
        for _ in range(3):
            salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        texto = self.rodar_comando()
        self.assertIn("Amostras: 3", texto)
        self.assertIn("Amostras válidas: 3", texto)
        self.assertIn("Amostras inválidas: 0", texto)

    def test_ignora_sinais_estaticos(self):
        estatico = Sinal.objects.create(titulo="Letra A")
        AmostraMovimento.objects.create(
            sinal=estatico, quantidade_frames=10, duracao_ms=660,
            arquivo_dados="movimentos/1/1.json", fps=15.2,
        )
        texto = self.rodar_comando()
        self.assertNotIn(f"SINAL #{estatico.pk}", texto)

    def test_resumo_por_sinal_com_dois_sinais(self):
        outro = Sinal.objects.create(titulo="Z", tipo=Sinal.Tipo.MOVIMENTO)
        salvar_amostra(self.sinal, self.gerar_sequencia(total=15))
        salvar_amostra(outro, self.gerar_sequencia(total=15))
        texto = self.rodar_comando()
        self.assertEqual(texto.count("SINAL #"), 2)
        self.assertEqual(texto.count("RESUMO"), 2)
        self.assertEqual(texto.count("Status do dataset"), 2)


class TemporalMLBase(VerificadorBase):
    """Base do pipeline temporal: modelo isolado no MEDIA_ROOT de teste."""

    def setUp(self):
        super().setUp()
        ajuste = patch(
            "libras.temporal.MODELO_PATH",
            Path(self.media_tmp) / "movimentos_teste.joblib",
        )
        ajuste.start()
        self.addCleanup(ajuste.stop)

    @staticmethod
    def trajetoria_sintetica(total=20, fase=0.0):
        """Trajetória suave de 63 valores por frame, variando no tempo."""
        return [
            [math.sin(i / 3 + fase + j / 10) for j in range(63)]
            for i in range(total)
        ]

    def salvar_trajetoria(self, sinal, vetores, intervalo_ms=66):
        sequencia = [
            {"timestamp_ms": i * intervalo_ms, "landmarks": list(vetor)}
            for i, vetor in enumerate(vetores)
        ]
        return salvar_amostra(sinal, sequencia)

    def treinar_padrao(self, sinal, total=5, passo_fase=0.05):
        """Cria `total` amostras da mesma forma e treina o modelo."""
        pks = []
        for indice in range(total):
            amostra = self.salvar_trajetoria(
                sinal, self.trajetoria_sintetica(fase=indice * passo_fase)
            )
            pks.append(amostra.pk)
        return temporal.treinar(), pks

    @staticmethod
    def trajetoria_nao_j(total=36):
        """Sequência deliberadamente diferente de J (Etapa 4.3).

        DADO SINTÉTICO DE TESTE: mão fechada abrindo em leque com
        leve rotação — muda a forma relativa da mão, que é o que a
        normalização preserva (translação do punho é descartada).
        """
        frames = []
        for indice in range(total):
            t = indice / (total - 1)
            pontos = [[0.0, 0.0, 0.0]]  # pulso na origem
            for k in range(1, 21):
                angulo = (k % 5) * (2 * math.pi / 5) + (k // 5) * 0.3 + 0.7 * t
                raio = 0.12 + 0.78 * t  # fechada → aberta
                pontos.append(
                    [raio * math.cos(angulo), raio * math.sin(angulo), 0.0]
                )
            frames.append([valor for ponto in pontos for valor in ponto])
        return frames

    @staticmethod
    def conteudo_json(vetores, sinal_id=None, intervalo_ms=66):
        """Conteúdo JSON no formato das amostras (Etapa 4.1)."""
        total = len(vetores)
        duracao = (total - 1) * intervalo_ms
        return {
            "version": 1,
            "sinal_id": sinal_id,
            "quantidade_frames": total,
            "quantidade_frames_validos": total,
            "duracao_ms": duracao,
            "fps": round((total - 1) / (duracao / 1000), 1) if duracao else 0.0,
            "quantidade_landmarks": 21,
            "frames": [
                {"timestamp_ms": i * intervalo_ms, "landmarks": list(vetor)}
                for i, vetor in enumerate(vetores)
            ],
        }

    def escrever_externo(self, vetores, sinal_id=None):
        """Grava um JSON externo de teste no MEDIA_ROOT temporário."""
        caminho = Path(self.media_tmp) / "externo.json"
        caminho.write_text(
            json.dumps(self.conteudo_json(vetores, sinal_id=sinal_id)),
            encoding="utf-8",
        )
        return caminho


def mao_sintetica(t, dx=0.0, dy=0.0, giro=0.0, tamanho=0.15):
    """63 valores crus de uma mão plausível em coordenadas de imagem.

    O pulso fica em (0.5 + dx, 0.5 + dy); os demais pontos giram em
    torno dele conforme ``t`` e ``giro`` — muda a forma relativa.
    """
    pulso = (0.5 + dx, 0.5 + dy)
    valores = [pulso[0], pulso[1], 0.0]
    for k in range(1, 21):
        angulo = (k % 5) * 0.5 + (k // 5) * 0.2 + giro * t - 1.0
        raio = tamanho * (0.4 + 0.15 * (k // 5 + 1))
        valores.extend((
            pulso[0] + raio * math.cos(angulo),
            pulso[1] - raio * math.sin(angulo),
            0.01 * k * tamanho,
        ))
    return valores


def frames_de(vetores, intervalo_ms=66, mao=None):
    """Lista de vetores crus → frames no formato das amostras."""
    return [
        {"timestamp_ms": i * intervalo_ms, "landmarks": list(v), "mao": mao}
        for i, v in enumerate(vetores)
    ]


class NormalizacaoEProcessamentoTests(TemporalMLBase):
    """Conversão de frames crus em trajetórias (features do formato 2)."""

    @staticmethod
    def gesto(total=20, deslocamento=(0.0, 0.0), giro=1.5):
        return [
            mao_sintetica(
                i / (total - 1),
                dx=deslocamento[0] * i / (total - 1),
                dy=deslocamento[1] * i / (total - 1),
                giro=giro,
            )
            for i in range(total)
        ]

    def test_normalizacao_invariante_a_translacao_e_escala(self):
        bruto = [math.sin(j / 10) for j in range(63)]
        deslocado = [valor + 10 for valor in bruto]
        escalado = [valor * 3 for valor in bruto]
        self.assertTrue(
            np.allclose(normalizar_frame(bruto), normalizar_frame(deslocado))
        )
        self.assertTrue(
            np.allclose(normalizar_frame(bruto), normalizar_frame(escalado))
        )

    def test_passo_tem_forma_e_deslocamento_do_pulso(self):
        trajetoria = processar_frames(frames_de(self.gesto()))
        self.assertTrue(trajetoria)
        self.assertTrue(
            all(len(passo) == temporal.VALORES_POR_PASSO for passo in trajetoria)
        )
        # O deslocamento do pulso é medido desde o início do gesto.
        self.assertEqual(trajetoria[0][-2:], [0.0, 0.0])

    def test_deslocamento_do_pulso_diferencia_mesma_forma(self):
        """Mesma forma, braço desenhando o movimento (caso do Z)."""
        parado = processar_frames(frames_de(self.gesto(giro=0.0)))
        andando = processar_frames(
            frames_de(self.gesto(deslocamento=(0.3, 0.2), giro=0.0))
        )
        # A forma (63 primeiros valores) é idêntica nas duas...
        self.assertTrue(np.allclose(
            np.asarray(parado)[0, :63], np.asarray(andando)[0, :63]
        ))
        # ...mas o deslocamento do pulso as separa.
        self.assertGreater(distancia_dtw(parado, andando), 0.5)

    def test_deslocamento_em_tamanhos_de_mao(self):
        pequena = [
            mao_sintetica(0.0, dx=0.2 * i / 19, tamanho=0.1) for i in range(20)
        ]
        grande = [
            mao_sintetica(0.0, dx=0.4 * i / 19, tamanho=0.2) for i in range(20)
        ]
        a = np.asarray(processar_frames(frames_de(pequena)))
        b = np.asarray(processar_frames(frames_de(grande)))
        # Mão duas vezes maior (mais perto da câmera) andando o dobro:
        # o mesmo gesto em tamanhos de mão.
        self.assertTrue(np.allclose(a, b))

    def test_mao_esquerda_e_espelhada(self):
        direita = self.gesto(deslocamento=(0.2, 0.1))
        espelhada = [
            [1.0 - v if k % 3 == 0 else v for k, v in enumerate(frame)]
            for frame in direita
        ]
        a = processar_frames(frames_de(direita, mao="Right"))
        b = processar_frames(frames_de(espelhada, mao="Left"))
        self.assertTrue(np.allclose(a, b))

    def test_reamostra_para_passo_fixo(self):
        # Mesma duração (1254 ms) amostrada a ~30 fps e a ~15 fps.
        lento = processar_frames(frames_de(self.gesto(total=39), intervalo_ms=33))
        normal = processar_frames(frames_de(self.gesto(total=20), intervalo_ms=66))
        self.assertLessEqual(abs(len(lento) - len(normal)), 1)
        self.assertLess(distancia_dtw(lento, normal), 0.05)

    def test_apara_repouso_nas_pontas(self):
        gesto = self.gesto(deslocamento=(0.3, 0.0))
        com_espera = [gesto[0]] * 12 + gesto + [gesto[-1]] * 12
        aparado = processar_frames(frames_de(com_espera))
        limpo = processar_frames(frames_de(gesto))
        self.assertLessEqual(abs(len(aparado) - len(limpo)), 2)
        self.assertLess(distancia_dtw(aparado, limpo), 0.1)

    def test_lacunas_truncadas_nas_pontas_e_interpoladas_no_meio(self):
        bruta = self.trajetoria_sintetica(total=15)
        frames = frames_de(bruta)
        # Frames vazios: pontas (0, 1, 14) e meio (5, 6).
        for indice in (0, 1, 5, 6, 14):
            frames[indice]["landmarks"] = None
        tempos, crus, _ = temporal._preencher_lacunas(frames)
        # Pontas truncadas: restam os frames 2..13.
        self.assertEqual(tempos, [i * 66 for i in range(2, 14)])
        # Frame 5 interpolado por timestamp entre 4 e 7.
        peso = (5 - 4) / (7 - 4)
        esperado = [a + (b - a) * peso for a, b in zip(bruta[4], bruta[7])]
        self.assertTrue(np.allclose(crus[3], esperado))
        self.assertTrue(np.allclose(crus[2], bruta[4]))

    def test_sem_frames_validos_retorna_vazio(self):
        frames = frames_de(self.gesto(total=5))
        for frame in frames:
            frame["landmarks"] = None
        self.assertEqual(processar_frames(frames), [])


class DistanciaDTWTests(TemporalMLBase):
    """Comportamento básico da métrica de alinhamento temporal."""

    def test_zero_consigo_mesma_e_simetrica(self):
        a = self.trajetoria_sintetica(total=12)
        b = self.trajetoria_sintetica(total=15, fase=0.2)
        self.assertEqual(distancia_dtw(a, a), 0.0)
        self.assertAlmostEqual(distancia_dtw(a, b), distancia_dtw(b, a))

    def test_mesma_forma_com_ritmo_diferente_fica_proxima(self):
        rapida = [
            [math.sin(i / 3 + j / 10) for j in range(63)] for i in range(20)
        ]
        lenta = [
            [math.sin(i / 4.5 + j / 10) for j in range(63)] for i in range(30)
        ]
        deslocada = [
            [math.sin(i / 3 + 0.6 + j / 10) for j in range(63)]
            for i in range(20)
        ]
        self.assertLess(distancia_dtw(rapida, lenta), distancia_dtw(rapida, deslocada))


class TreinarModeloTests(TemporalMLBase):
    """treinar: memoriza trajetórias e calibra limiares por classe."""

    def test_salva_modelo_com_limiares_e_loo(self):
        treino, pks = self.treinar_padrao(self.sinal)
        modelo = temporal.carregar_modelo()
        self.assertEqual(modelo["classes"], ["J"])
        self.assertEqual(modelo["amostras_por_classe"]["J"], 5)
        self.assertEqual(
            sorted(t["amostra_id"] for t in modelo["templates"]["J"]),
            sorted(pks),
        )
        self.assertEqual(len(modelo["loo"]["J"]), 5)
        self.assertGreater(modelo["limiares"]["J"], 0)
        self.assertTrue(
            (Path(self.media_tmp) / "movimentos_teste.joblib").is_file()
        )

    def test_sem_amostras_validas_levanta_erro(self):
        with self.assertRaises(temporal.ErroTemporal):
            temporal.treinar()

    def test_ignora_amostras_invalidas(self):
        self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica())
        self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica(fase=0.05))
        ruim = self.salvar_trajetoria(
            self.sinal, self.trajetoria_sintetica(fase=0.10)
        )
        (Path(self.media_tmp) / ruim.arquivo_dados).unlink()
        treino = temporal.treinar()
        self.assertEqual(len(treino.invalidas), 1)
        self.assertEqual(treino.modelo["amostras_por_classe"]["J"], 2)

    def test_exclui_classe_com_unica_amostra(self):
        self.treinar_padrao(self.sinal)
        outro = Sinal.objects.create(titulo="K", tipo=Sinal.Tipo.MOVIMENTO)
        self.salvar_trajetoria(outro, self.trajetoria_sintetica(fase=9.9))
        treino = temporal.treinar()
        self.assertIn(("K", 1), treino.excluidas)
        self.assertEqual(treino.modelo["classes"], ["J"])

    def test_rejeita_quando_toda_classe_tem_uma_amostra(self):
        amostra = self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica())
        self.assertIsNotNone(amostra)
        with self.assertRaises(temporal.ErroTemporal):
            temporal.treinar()


class PreverTests(TemporalMLBase):
    """prever: vizinho mais próximo com limiar de rejeição.

    prever espera a trajetória já processada (como sai de
    processar_frames) — os templates do modelo saem de lá.
    """

    @staticmethod
    def normalizada(total=20, fase=0.0):
        return processar_frames(
            frames_de(TemporalMLBase.trajetoria_sintetica(total, fase))
        )

    def test_reconhece_trajetoria_nova_da_mesma_forma(self):
        treino, _ = self.treinar_padrao(self.sinal)
        previsao = prever(self.normalizada(fase=0.02), treino.modelo)
        self.assertEqual(previsao["previsto"], "J")
        self.assertTrue(previsao["reconhecido"])
        self.assertGreater(previsao["confianca"], 0)

    def test_rejeita_ruido(self):
        treino, _ = self.treinar_padrao(self.sinal)
        gerador = random.Random(42)
        ruido = processar_frames(frames_de(
            [[gerador.uniform(-3, 3) for _ in range(63)] for _ in range(20)]
        ))
        previsao = prever(ruido, treino.modelo)
        self.assertFalse(previsao["reconhecido"])
        self.assertEqual(previsao["confianca"], 0.0)

    def test_modo_loo_exclui_a_propria_amostra(self):
        treino, pks = self.treinar_padrao(self.sinal)
        previsao = prever(
            self.normalizada(fase=0.0), treino.modelo, excluir_amostra=pks[0]
        )
        self.assertNotEqual(previsao["vizinho_amostra"], pks[0])
        self.assertTrue(previsao["reconhecido"])


class TestarAmostraTests(TemporalMLBase):
    """testar_amostra: pipeline completo de teste de uma amostra real."""

    def test_reconhece_de_ponta_a_ponta(self):
        treino, pks = self.treinar_padrao(self.sinal)
        resultado = temporal.testar_amostra(pks[0])
        self.assertEqual(resultado["esperado"], "J")
        self.assertEqual(resultado["previsto"], "J")
        self.assertTrue(resultado["reconhecido"])
        self.assertTrue(resultado["modo_loo"])
        self.assertEqual(resultado["frames_processados"], 20)

    def test_amostra_fora_do_treino_nao_e_excluida(self):
        self.treinar_padrao(self.sinal)
        nova = self.salvar_trajetoria(
            self.sinal, self.trajetoria_sintetica(fase=0.02)
        )
        resultado = temporal.testar_amostra(nova.pk)
        self.assertFalse(resultado["modo_loo"])
        self.assertTrue(resultado["reconhecido"])

    def test_amostra_inexistente_levanta_erro(self):
        with self.assertRaises(temporal.ErroTemporal):
            temporal.testar_amostra(9999)

    def test_amostra_estruturalmente_invalida_levanta_erro(self):
        _, pks = self.treinar_padrao(self.sinal)
        amostra = AmostraMovimento.objects.get(pk=pks[0])
        (Path(self.media_tmp) / amostra.arquivo_dados).unlink()
        with self.assertRaises(temporal.ErroTemporal) as contexto:
            temporal.testar_amostra(pks[0])
        self.assertIn("inválida", str(contexto.exception))

    def test_sem_modelo_treinado_leciona_o_comando(self):
        amostra = self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica())
        with self.assertRaises(temporal.ErroTemporal) as contexto:
            temporal.testar_amostra(amostra.pk)
        self.assertIn("treinar_movimentos", str(contexto.exception))


class TreinarMovimentosCommandTests(TemporalMLBase):
    """Comando treinar_movimentos: relatório de treino no terminal."""

    def test_relatorio_de_treino_completo(self):
        self.treinar_padrao(self.sinal)
        saida = StringIO()
        call_command("treinar_movimentos", stdout=saida, no_color=True)
        texto = saida.getvalue()
        self.assertIn("=== TREINAMENTO DE MOVIMENTOS ===", texto)
        self.assertIn("Sinal: J", texto)
        self.assertIn("Amostras: 5", texto)
        self.assertIn("Avaliação leave-one-out", texto)
        self.assertIn("Limiar de rejeição de J", texto)
        self.assertIn("Modelo treinado com sucesso.", texto)
        self.assertIn("uma única classe", texto)
        self.assertIn("Não use em produção", texto)

    def test_sem_amostras_levanta_command_error(self):
        with self.assertRaises(CommandError):
            call_command("treinar_movimentos", stdout=StringIO())


class TestarMovimentoCommandTests(TemporalMLBase):
    """Comando testar_movimento: relatório de teste no terminal."""

    def test_relatorio_de_teste_reconhecido(self):
        _, pks = self.treinar_padrao(self.sinal)
        saida = StringIO()
        call_command(
            "testar_movimento", amostra=pks[0], stdout=saida, no_color=True
        )
        texto = saida.getvalue()
        self.assertIn("=== TESTE DE MOVIMENTO ===", texto)
        self.assertIn("Esperado: J", texto)
        self.assertIn("Previsto: J", texto)
        self.assertIn("Confiança:", texto)
        self.assertIn("Resultado: ✓ RECONHECEU", texto)
        self.assertIn("uma única classe", texto)

    def test_relatorio_de_teste_rejeitado(self):
        _, pks = self.treinar_padrao(self.sinal)
        amostra = AmostraMovimento.objects.get(pk=pks[0])
        gerador = random.Random(7)
        conteudo = {
            "version": FORMATO_VERSAO,
            "sinal_id": self.sinal.pk,
            "quantidade_frames": 20,
            "quantidade_frames_validos": 20,
            "duracao_ms": 19 * 66,
            "fps": round(19 / (19 * 66 / 1000), 1),
            "quantidade_landmarks": 21,
            "frames": [
                {
                    "timestamp_ms": i * 66,
                    "landmarks": [gerador.uniform(-3, 3) for _ in range(63)],
                }
                for i in range(20)
            ],
        }
        self.escrever_arquivo(amostra, conteudo)
        saida = StringIO()
        call_command(
            "testar_movimento", amostra=pks[0], stdout=saida, no_color=True
        )
        texto = saida.getvalue()
        self.assertIn("Resultado: ✗ NÃO RECONHECEU", texto)

    def test_sem_flag_lista_amostras_disponiveis(self):
        self.treinar_padrao(self.sinal)
        saida = StringIO()
        call_command("testar_movimento", stdout=saida, no_color=True)
        texto = saida.getvalue()
        self.assertIn("Amostras disponíveis:", texto)
        self.assertIn("--amostra", texto)

    def test_amostra_inexistente_levanta_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "testar_movimento", amostra=9999, stdout=StringIO()
            )


class VerificarConteudoTests(TemporalMLBase):
    """verificar_conteudo: validação standalone, sem o banco (Etapa 4.3)."""

    def test_conteudo_valido_sem_vinculo_com_sinal(self):
        conteudo = self.conteudo_json(self.trajetoria_sintetica(), sinal_id=None)
        resultado = verificar_conteudo(conteudo)
        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.problemas, [])

    def test_sinal_id_ignorado_quando_nao_esperado(self):
        conteudo = self.conteudo_json(self.trajetoria_sintetica(), sinal_id=999)
        resultado = verificar_conteudo(conteudo)
        self.assertTrue(resultado.ok)

    def test_sinal_id_conferido_quando_esperado(self):
        conteudo = self.conteudo_json(self.trajetoria_sintetica(), sinal_id=999)
        resultado = verificar_conteudo(conteudo, sinal_id_esperado=1)
        self.assertFalse(resultado.ok)
        self.assertIn("sinal_id do arquivo", resultado.problemas[0])

    def test_poucos_frames_validos_sem_banco(self):
        vetores = self.trajetoria_sintetica(total=15)
        conteudo = self.conteudo_json(vetores)
        for frame in conteudo["frames"][:8]:
            frame["landmarks"] = None
        conteudo["quantidade_frames_validos"] = 7
        resultado = verificar_conteudo(conteudo)
        self.assertFalse(resultado.ok)
        self.assertIn(
            f"apenas 7 frames válidos (mínimo {FRAMES_MIN_VALIDOS})",
            resultado.problemas,
        )


class TestarArquivoTests(TemporalMLBase):
    """testar_arquivo: entrada externa de não-J contra o modelo.

    A entrada externa nunca esteve nos templates — é o teste
    controlado de rejeição da Etapa 4.3.
    """

    def test_rejeita_movimento_deliberadamente_diferente(self):
        self.treinar_padrao(self.sinal)
        caminho = self.escrever_externo(self.trajetoria_nao_j())
        resultado = temporal.testar_arquivo(str(caminho))
        self.assertEqual(resultado["esperado"], "não-J")
        self.assertFalse(resultado["modo_loo"])
        self.assertFalse(resultado["reconhecido"])
        self.assertEqual(resultado["confianca"], 0.0)
        self.assertGreater(resultado["distancia"], resultado["limiar"])

    def test_aceita_entrada_com_a_mesma_forma_do_treino(self):
        self.treinar_padrao(self.sinal)
        caminho = self.escrever_externo(self.trajetoria_sintetica(fase=0.02))
        resultado = temporal.testar_arquivo(str(caminho))
        self.assertEqual(resultado["previsto"], "J")
        self.assertTrue(resultado["reconhecido"])
        self.assertEqual(resultado["frames_processados"], 20)

    def test_arquivo_inexistente_levanta_erro(self):
        with self.assertRaises(temporal.ErroTemporal) as contexto:
            temporal.testar_arquivo(
                str(Path(self.media_tmp) / "nao_existe.json")
            )
        self.assertIn("não encontrado", str(contexto.exception))

    def test_json_corrompido_levanta_erro(self):
        caminho = Path(self.media_tmp) / "externo.json"
        caminho.write_text("não é json", encoding="utf-8")
        with self.assertRaises(temporal.ErroTemporal) as contexto:
            temporal.testar_arquivo(str(caminho))
        self.assertIn("JSON inválido", str(contexto.exception))

    def test_estrutura_incompleta_levanta_erro(self):
        caminho = Path(self.media_tmp) / "externo.json"
        caminho.write_text(json.dumps({"version": 1}), encoding="utf-8")
        with self.assertRaises(temporal.ErroTemporal) as contexto:
            temporal.testar_arquivo(str(caminho))
        self.assertIn("estruturalmente inválido", str(contexto.exception))

    def test_metadados_incoerentes_levanta_erro(self):
        caminho = self.escrever_externo(self.trajetoria_sintetica(fase=0.02))
        conteudo = json.loads(caminho.read_text(encoding="utf-8"))
        conteudo["quantidade_frames"] = 99
        caminho.write_text(json.dumps(conteudo), encoding="utf-8")
        with self.assertRaises(temporal.ErroTemporal) as contexto:
            temporal.testar_arquivo(str(caminho))
        self.assertIn("difere do real", str(contexto.exception))


class TestarMovimentoArquivoCommandTests(TemporalMLBase):
    """Comando testar_movimento --arquivo: relatório de rejeição."""

    def rodar_arquivo(self, vetores):
        caminho = self.escrever_externo(vetores)
        saida = StringIO()
        call_command(
            "testar_movimento", arquivo=str(caminho), stdout=saida, no_color=True
        )
        return saida.getvalue()

    def test_relatorio_de_nao_j_rejeitado(self):
        self.treinar_padrao(self.sinal)
        texto = self.rodar_arquivo(self.trajetoria_nao_j())
        self.assertIn("TESTE DE MOVIMENTO (ARQUIVO EXTERNO)", texto)
        self.assertIn("Esperado: não-J", texto)
        self.assertIn("Previsto: REJEITADO", texto)
        self.assertIn("Resultado: ✓ REJEITOU", texto)
        self.assertIn("limiar DTW", texto)

    def test_relatorio_de_falso_positivo(self):
        self.treinar_padrao(self.sinal)
        texto = self.rodar_arquivo(self.trajetoria_sintetica(fase=0.02))
        self.assertIn("Previsto: J", texto)
        self.assertIn("FALSO POSITIVO", texto)
        self.assertIn("ACEITOU", texto)

    def test_amostra_e_arquivo_sao_mutuamente_exclusivos(self):
        with self.assertRaises(CommandError):
            call_command(
                "testar_movimento",
                amostra=1,
                arquivo="qualquer.json",
                stdout=StringIO(),
            )

    def test_listagem_explica_os_dois_modos(self):
        saida = StringIO()
        call_command("testar_movimento", stdout=saida, no_color=True)
        texto = saida.getvalue()
        self.assertIn("--amostra <id>", texto)
        self.assertIn("--arquivo <caminho>", texto)


class ExemplosNegativosTests(TemporalMLBase):
    """Sinais marcados como negativos ensinam o modelo a rejeitar."""

    def setUp(self):
        super().setUp()
        self.negativo = Sinal.objects.create(
            titulo="J incompleto", tipo=Sinal.Tipo.MOVIMENTO, negativo=True
        )

    def gravar_negativos(self, *fases):
        return [
            self.salvar_trajetoria(self.negativo, self.trajetoria_sintetica(fase=f))
            for f in fases
        ]

    @staticmethod
    def processada(fase):
        return processar_frames(
            frames_de(TemporalMLBase.trajetoria_sintetica(fase=fase))
        )

    def test_form_aceita_negativo_de_movimento(self):
        form = SinalForm(data={
            "titulo": "I parado", "tipo": Sinal.Tipo.MOVIMENTO, "negativo": "on",
        })
        self.assertTrue(form.is_valid())
        self.assertTrue(form.save().negativo)

    def test_form_rejeita_negativo_estatico(self):
        form = SinalForm(data={
            "titulo": "X", "tipo": Sinal.Tipo.ESTATICO, "negativo": "on",
        })
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Exemplos negativos precisam ser do tipo movimento.",
            form.errors["negativo"],
        )

    def test_negativos_nao_viram_classe(self):
        self.gravar_negativos(0.8, 0.85)
        treino, _ = self.treinar_padrao(self.sinal)
        self.assertEqual(treino.modelo["classes"], ["J"])
        self.assertEqual(len(treino.modelo["negativos"]), 2)
        self.assertEqual(treino.modelo["negativos"][0]["sinal"], "J incompleto")

    def test_somente_negativos_nao_treina(self):
        self.gravar_negativos(0.8, 0.85)
        with self.assertRaises(temporal.ErroTemporal):
            temporal.treinar()

    def test_negativo_aperta_o_limiar(self):
        sem_negativo, _ = self.treinar_padrao(self.sinal)
        limiar_original = sem_negativo.modelo["limiares"]["J"]
        self.gravar_negativos(0.5)
        modelo = temporal.treinar().modelo
        calibracao = modelo["calibracao"]["J"]
        tipica = float(np.median([e["distancia"] for e in modelo["loo"]["J"]]))
        self.assertFalse(calibracao["sobreposicao"])
        self.assertLessEqual(modelo["limiares"]["J"], limiar_original)
        self.assertLessEqual(
            modelo["limiares"]["J"], (tipica + calibracao["negativo_min"]) / 2 + 1e-9
        )
        self.assertGreaterEqual(modelo["limiares"]["J"], tipica)

    def test_rejeita_quando_negativo_e_mais_parecido(self):
        self.gravar_negativos(0.07)
        treino, _ = self.treinar_padrao(self.sinal)
        self.assertTrue(treino.modelo["calibracao"]["J"]["sobreposicao"])
        previsao = prever(self.processada(0.07), treino.modelo)
        self.assertFalse(previsao["reconhecido"])
        self.assertEqual(previsao["motivo_rejeicao"], "negativo")
        self.assertEqual(previsao["confianca"], 0.0)
        self.assertEqual(previsao["negativo_mais_proximo"]["sinal"], "J incompleto")

    def test_sinal_real_continua_reconhecido(self):
        self.gravar_negativos(0.8)
        treino, _ = self.treinar_padrao(self.sinal)
        previsao = prever(self.processada(0.02), treino.modelo)
        self.assertTrue(previsao["reconhecido"])
        self.assertIsNone(previsao["motivo_rejeicao"])

    def test_testar_amostra_negativa_em_leave_one_out(self):
        pks = [a.pk for a in self.gravar_negativos(0.07, 0.08)]
        self.treinar_padrao(self.sinal)
        resultado = temporal.testar_amostra(pks[0])
        self.assertTrue(resultado["negativo"])
        self.assertTrue(resultado["modo_loo"])
        self.assertNotEqual(resultado["negativo_mais_proximo"]["amostra"], pks[0])

    def test_comandos_relatam_negativos(self):
        pks = [a.pk for a in self.gravar_negativos(0.07, 0.08)]
        self.treinar_padrao(self.sinal)
        saida = StringIO()
        call_command("treinar_movimentos", stdout=saida, no_color=True)
        texto = saida.getvalue()
        self.assertIn("Exemplos negativos (ensinam a rejeitar):", texto)
        self.assertIn("J incompleto: 2 amostra(s)", texto)
        self.assertIn("ajustado pelo negativo mais próximo", texto)
        saida = StringIO()
        call_command("testar_movimento", amostra=pks[0], stdout=saida, no_color=True)
        texto = saida.getvalue()
        self.assertIn("exemplo negativo", texto)
        self.assertIn("Esperado: REJEITADO", texto)
        self.assertIn("Negativo mais próximo: J incompleto", texto)
        self.assertIn("Resultado: ✓ REJEITOU", texto)

    def test_paginas_exibem_negativo(self):
        response = self.client.get(reverse("gestos"))
        self.assertContains(response, "negativo")
        response = self.client.get(reverse("gesto_detalhe", args=[self.negativo.pk]))
        self.assertContains(response, "exemplo negativo")
        response = self.client.get(reverse("gesto_novo"))
        self.assertContains(response, "Exemplo negativo")


class DetectorAoVivoTests(TemporalMLBase):
    """Segmentação e reconhecimento de movimentos frame a frame."""

    PASSO_MS = 33  # câmera ao vivo ~30 fps

    @staticmethod
    def gesto(total, variacao=0.0):
        return [
            mao_sintetica(
                i / (total - 1),
                dx=(0.3 + variacao) * i / (total - 1),
                giro=3.0 + variacao,
            )
            for i in range(total)
        ]

    def treinar_gesto(self):
        for indice in range(5):
            frames = frames_de(self.gesto(20, variacao=indice * 0.02))
            for frame in frames:
                frame["mao"] = None
            salvar_amostra(self.sinal, frames)
        return temporal.treinar()

    def alimentar(self, detector, vetores, inicio_ms=0):
        """Envia os frames ao detector; devolve [(ms, previsão)]."""
        saidas = []
        for indice, vetor in enumerate(vetores):
            ms = inicio_ms + indice * self.PASSO_MS
            previsao = detector.observar(ms, vetor, "Right" if vetor else None)
            if previsao is not None:
                saidas.append((ms, previsao))
        return saidas

    def detector(self):
        return DetectorMovimento(Path(self.media_tmp) / "movimentos_teste.joblib")

    def test_reconhece_gesto_entre_pausas(self):
        self.treinar_gesto()
        gesto = self.gesto(40, variacao=0.01)  # ~1,3 s a 30 fps
        sequencia = [gesto[0]] * 20 + gesto + [gesto[-1]] * 20
        saidas = self.alimentar(self.detector(), sequencia)
        self.assertEqual(len(saidas), 1)
        _, previsao = saidas[0]
        self.assertEqual(previsao["previsto"], "J")
        self.assertTrue(previsao["reconhecido"])

    def test_mao_parada_nao_dispara(self):
        self.treinar_gesto()
        parada = [self.gesto(20)[5]] * 90
        self.assertEqual(self.alimentar(self.detector(), parada), [])

    def test_mao_saindo_do_quadro_encerra_o_movimento(self):
        self.treinar_gesto()
        gesto = self.gesto(40, variacao=0.01)
        sequencia = [gesto[0]] * 10 + gesto + [None] * 20
        saidas = self.alimentar(self.detector(), sequencia)
        self.assertEqual(len(saidas), 1)
        self.assertTrue(saidas[0][1]["reconhecido"])

    def test_tremor_curto_e_ignorado(self):
        self.treinar_gesto()
        base = self.gesto(20)
        # Um solavanco de 3 frames: abaixo da duração mínima.
        sequencia = [base[0]] * 20 + [base[10], base[0], base[10]] + [base[0]] * 20
        self.assertEqual(self.alimentar(self.detector(), sequencia), [])

    def test_sem_modelo_nao_quebra(self):
        detector = self.detector()
        gesto = self.gesto(40)
        sequencia = [gesto[0]] * 10 + gesto + [gesto[-1]] * 20
        self.assertEqual(self.alimentar(detector, sequencia), [])
        self.assertFalse(detector.pronto)
        self.assertIn("não treinado", detector.erro)

    def test_recarrega_modelo_retreinado(self):
        detector = self.detector()
        self.assertFalse(detector.pronto)
        self.treinar_gesto()
        self.assertTrue(detector.pronto)

    def test_status_informa_movimento(self):
        response = self.client.get(reverse("status"))
        payload = response.json()
        self.assertIn("movement_ready", payload)
        self.assertIn("movement_label", payload)


class SegmentacaoGravacaoTests(TemporalMLBase):
    """Recorte do movimento principal das gravações (treino ≡ ao vivo)."""

    @staticmethod
    def gesto(total):
        return [
            mao_sintetica(i / (total - 1), dx=0.3 * i / (total - 1), giro=3.0)
            for i in range(total)
        ]

    def gravacao(self):
        """Mão entra (solavanco), espera, faz o gesto, espera, sai."""
        gesto = self.gesto(20)
        entrada = [mao_sintetica(0.0, dy=0.3 - 0.1 * i) for i in range(3)]
        return frames_de(
            entrada + [gesto[0]] * 15 + gesto + [gesto[-1]] * 15
            + [mao_sintetica(1.0, dx=0.3, dy=0.1 * i, giro=3.0) for i in range(3)]
        )

    def test_encontra_o_gesto_e_descarta_entrada_e_saida(self):
        frames = self.gravacao()
        trecho = temporal.trecho_principal(frames)
        inicio_gesto, fim_gesto = 18 * 66, (18 + 19) * 66
        self.assertLessEqual(trecho[0]["timestamp_ms"], inicio_gesto)
        self.assertGreaterEqual(
            trecho[0]["timestamp_ms"], inicio_gesto - temporal.PRE_MOVIMENTO_MS
        )
        self.assertGreaterEqual(trecho[-1]["timestamp_ms"], fim_gesto - 66)
        self.assertLess(trecho[-1]["timestamp_ms"], fim_gesto + 5 * 66)

    def test_sem_movimento_usa_a_gravacao_inteira(self):
        parada = frames_de([mao_sintetica(0.0)] * 20)
        self.assertEqual(temporal.trecho_principal(parada), parada)

    def test_movimento_ate_o_fim_da_gravacao_e_fechado(self):
        frames = frames_de([self.gesto(20)[0]] * 10 + self.gesto(20))
        self.assertEqual(len(temporal.segmentos(frames)), 1)

    def test_processar_sequencia_usa_o_trecho_principal(self):
        frames = self.gravacao()
        conteudo = {"frames": frames}
        self.assertEqual(
            temporal.processar_sequencia(conteudo),
            processar_frames(temporal.trecho_principal(frames)),
        )
