"""Amostras de movimento: persistência, validação dos quadros e verificação."""
from pathlib import Path

from django.test import TestCase

from libras.models import AmostraMovimento, Sinal
from libras.movimento.amostras import (
    FORMATO_VERSAO,
    FRAMES_MIN_VALIDOS,
    AmostraInvalida,
    apagar_amostra,
    ler_sequencia,
    salvar_amostra,
    sequencia_de_gravacao,
    validar_marcos,
    validar_quadros,
)
from libras.movimento.verificacao import resumir, verificar_amostra, verificar_conteudo

from .base import TemporalBase, VerificadorBase, TemporalMLBase


class AmostraMovimentoTests(TemporalBase):
    """Serviço de amostras: validação, persistência fora do banco e leitura."""

    def test_salvar_cria_registro_e_arquivo_json(self):
        amostra = salvar_amostra(self.sinal, self.gerar_sequencia(15))
        self.assertEqual(AmostraMovimento.objects.count(), 1)
        self.assertEqual(amostra.sinal, self.sinal)
        self.assertEqual(
            amostra.arquivo_dados, f"{self.sinal.pk}-j/{amostra.pk}.json"
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


class ValidarQuadrosTests(TestCase):
    """Nada vindo do navegador é aceito sem checagem."""

    def test_marcos_validos_viram_float(self):
        self.assertEqual(validar_marcos([1] * 63), [1.0] * 63)
        self.assertIsNone(validar_marcos(None))

    def test_marcos_invalidos(self):
        for ruim in ([0.5] * 62, [0.5] * 64, "abc", [True] * 63, [None] * 63,
                     [float("nan")] * 63, [float("inf")] * 63, [11.0] * 63):
            with self.subTest(ruim=str(ruim)[:30]):
                with self.assertRaises(AmostraInvalida):
                    validar_marcos(ruim)

    def test_converte_para_o_formato_das_amostras(self):
        quadros = validar_quadros([
            {"t": 10.6, "marcos": [0.5] * 63, "mao": "Left"},
            {"t": 20, "marcos": None, "mao": "Right"},
        ])
        self.assertEqual(quadros[0], {"timestamp_ms": 10, "landmarks": [0.5] * 63, "mao": "Left"})
        # Sem pontos, a mão informada é descartada.
        self.assertEqual(quadros[1], {"timestamp_ms": 20, "landmarks": None, "mao": None})

    def test_quadros_invalidos(self):
        casos = [None, [], {"t": 1}, [1, 2], [{"t": -1, "marcos": None}],
                 [{"t": "1", "marcos": None}], [{"t": True, "marcos": None}],
                 [{"t": 5, "marcos": None}, {"t": 4, "marcos": None}],
                 [{"t": 1, "marcos": None, "mao": "Meio"}]]
        for ruim in casos:
            with self.subTest(ruim=str(ruim)[:40]):
                with self.assertRaises(AmostraInvalida):
                    validar_quadros(ruim)

    def test_maximo_de_quadros(self):
        with self.assertRaises(AmostraInvalida):
            validar_quadros([{"t": i, "marcos": None} for i in range(4)], maximo=3)

    def test_gravacao_comeca_no_zero(self):
        sequencia = sequencia_de_gravacao([{"t": 1000, "marcos": None}, {"t": 1033, "marcos": None}])
        self.assertEqual([q["timestamp_ms"] for q in sequencia], [0, 33])


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
