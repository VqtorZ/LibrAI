"""Movimento: trajetória, segmentação, DTW, treino, previsão e negativos."""
import json
import math
import random
from io import StringIO
from pathlib import Path

import numpy as np
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from libras.forms import SinalForm
from libras.models import AmostraMovimento, Sinal
from libras.movimento import classificador, segmentacao, trajetoria
from libras.movimento.amostras import (
    FORMATO_VERSAO,
)
from libras.movimento.classificador import distancia_dtw, prever
from libras.movimento.trajetoria import normalizar_frame, processar_frames

from .base import TemporalMLBase, mao_sintetica, frames_de


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
        passos = processar_frames(frames_de(self.gesto()))
        self.assertTrue(passos)
        self.assertTrue(
            all(len(passo) == trajetoria.VALORES_POR_PASSO for passo in passos)
        )
        # O deslocamento do pulso é medido desde o início do gesto.
        self.assertEqual(passos[0][-2:], [0.0, 0.0])

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
        tempos, crus, _ = trajetoria._preencher_lacunas(frames)
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
        trecho = segmentacao.trecho_principal(frames)
        inicio_gesto, fim_gesto = 18 * 66, (18 + 19) * 66
        self.assertLessEqual(trecho[0]["timestamp_ms"], inicio_gesto)
        self.assertGreaterEqual(
            trecho[0]["timestamp_ms"], inicio_gesto - segmentacao.PRE_MOVIMENTO_MS
        )
        self.assertGreaterEqual(trecho[-1]["timestamp_ms"], fim_gesto - 66)
        self.assertLess(trecho[-1]["timestamp_ms"], fim_gesto + 5 * 66)

    def test_sem_movimento_usa_a_gravacao_inteira(self):
        parada = frames_de([mao_sintetica(0.0)] * 20)
        self.assertEqual(segmentacao.trecho_principal(parada), parada)

    def test_movimento_ate_o_fim_da_gravacao_e_fechado(self):
        frames = frames_de([self.gesto(20)[0]] * 10 + self.gesto(20))
        self.assertEqual(len(segmentacao.segmentos(frames)), 1)

    def test_processar_sequencia_usa_o_trecho_principal(self):
        frames = self.gravacao()
        conteudo = {"frames": frames}
        self.assertEqual(
            classificador.processar_sequencia(conteudo),
            processar_frames(segmentacao.trecho_principal(frames)),
        )


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
        modelo = classificador.carregar_modelo()
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
        with self.assertRaises(classificador.ErroTemporal):
            classificador.treinar()

    def test_ignora_amostras_invalidas(self):
        self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica())
        self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica(fase=0.05))
        ruim = self.salvar_trajetoria(
            self.sinal, self.trajetoria_sintetica(fase=0.10)
        )
        (Path(self.media_tmp) / ruim.arquivo_dados).unlink()
        treino = classificador.treinar()
        self.assertEqual(len(treino.invalidas), 1)
        self.assertEqual(treino.modelo["amostras_por_classe"]["J"], 2)

    def test_exclui_classe_com_unica_amostra(self):
        self.treinar_padrao(self.sinal)
        outro = Sinal.objects.create(titulo="K", tipo=Sinal.Tipo.MOVIMENTO)
        self.salvar_trajetoria(outro, self.trajetoria_sintetica(fase=9.9))
        treino = classificador.treinar()
        self.assertIn(("K", 1), treino.excluidas)
        self.assertEqual(treino.modelo["classes"], ["J"])

    def test_rejeita_quando_toda_classe_tem_uma_amostra(self):
        amostra = self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica())
        self.assertIsNotNone(amostra)
        with self.assertRaises(classificador.ErroTemporal):
            classificador.treinar()


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
        resultado = classificador.testar_amostra(pks[0])
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
        resultado = classificador.testar_amostra(nova.pk)
        self.assertFalse(resultado["modo_loo"])
        self.assertTrue(resultado["reconhecido"])

    def test_amostra_inexistente_levanta_erro(self):
        with self.assertRaises(classificador.ErroTemporal):
            classificador.testar_amostra(9999)

    def test_amostra_estruturalmente_invalida_levanta_erro(self):
        _, pks = self.treinar_padrao(self.sinal)
        amostra = AmostraMovimento.objects.get(pk=pks[0])
        (Path(self.media_tmp) / amostra.arquivo_dados).unlink()
        with self.assertRaises(classificador.ErroTemporal) as contexto:
            classificador.testar_amostra(pks[0])
        self.assertIn("inválida", str(contexto.exception))

    def test_sem_modelo_treinado_leciona_o_comando(self):
        amostra = self.salvar_trajetoria(self.sinal, self.trajetoria_sintetica())
        with self.assertRaises(classificador.ErroTemporal) as contexto:
            classificador.testar_amostra(amostra.pk)
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


class TestarArquivoTests(TemporalMLBase):
    """testar_arquivo: entrada externa de não-J contra o modelo.

    A entrada externa nunca esteve nos templates — é o teste
    controlado de rejeição da Etapa 4.3.
    """

    def test_rejeita_movimento_deliberadamente_diferente(self):
        self.treinar_padrao(self.sinal)
        caminho = self.escrever_externo(self.trajetoria_nao_j())
        resultado = classificador.testar_arquivo(str(caminho))
        self.assertEqual(resultado["esperado"], "não-J")
        self.assertFalse(resultado["modo_loo"])
        self.assertFalse(resultado["reconhecido"])
        self.assertEqual(resultado["confianca"], 0.0)
        self.assertGreater(resultado["distancia"], resultado["limiar"])

    def test_aceita_entrada_com_a_mesma_forma_do_treino(self):
        self.treinar_padrao(self.sinal)
        caminho = self.escrever_externo(self.trajetoria_sintetica(fase=0.02))
        resultado = classificador.testar_arquivo(str(caminho))
        self.assertEqual(resultado["previsto"], "J")
        self.assertTrue(resultado["reconhecido"])
        self.assertEqual(resultado["frames_processados"], 20)

    def test_arquivo_inexistente_levanta_erro(self):
        with self.assertRaises(classificador.ErroTemporal) as contexto:
            classificador.testar_arquivo(
                str(Path(self.media_tmp) / "nao_existe.json")
            )
        self.assertIn("não encontrado", str(contexto.exception))

    def test_json_corrompido_levanta_erro(self):
        caminho = Path(self.media_tmp) / "externo.json"
        caminho.write_text("não é json", encoding="utf-8")
        with self.assertRaises(classificador.ErroTemporal) as contexto:
            classificador.testar_arquivo(str(caminho))
        self.assertIn("JSON inválido", str(contexto.exception))

    def test_estrutura_incompleta_levanta_erro(self):
        caminho = Path(self.media_tmp) / "externo.json"
        caminho.write_text(json.dumps({"version": 1}), encoding="utf-8")
        with self.assertRaises(classificador.ErroTemporal) as contexto:
            classificador.testar_arquivo(str(caminho))
        self.assertIn("estruturalmente inválido", str(contexto.exception))

    def test_metadados_incoerentes_levanta_erro(self):
        caminho = self.escrever_externo(self.trajetoria_sintetica(fase=0.02))
        conteudo = json.loads(caminho.read_text(encoding="utf-8"))
        conteudo["quantidade_frames"] = 99
        caminho.write_text(json.dumps(conteudo), encoding="utf-8")
        with self.assertRaises(classificador.ErroTemporal) as contexto:
            classificador.testar_arquivo(str(caminho))
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
        with self.assertRaises(classificador.ErroTemporal):
            classificador.treinar()

    def test_negativo_aperta_o_limiar(self):
        sem_negativo, _ = self.treinar_padrao(self.sinal)
        limiar_original = sem_negativo.modelo["limiares"]["J"]
        self.gravar_negativos(0.5)
        modelo = classificador.treinar().modelo
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
        resultado = classificador.testar_amostra(pks[0])
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
        self.assertContains(response, "Negativo")
        response = self.client.get(reverse("gesto_detalhe", args=[self.negativo.pk]))
        self.assertContains(response, "EXEMPLO NEGATIVO")
        self.assertContains(response, "<strong>rejeitar</strong>", html=False)
        response = self.client.get(reverse("gesto_novo"))
        self.assertContains(response, "Exemplo negativo")
