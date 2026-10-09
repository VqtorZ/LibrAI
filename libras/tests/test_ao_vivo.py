"""Reconhecimento ao vivo: detector, sessões por aba e a API de quadros."""
import json

from django.urls import reverse

from libras.movimento import sessoes

from .base import AoVivoBase


class DetectorAoVivoTests(AoVivoBase):
    """Segmentação e reconhecimento de movimentos frame a frame."""

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


class DiagnosticoAoVivoTests(AoVivoBase):
    """Registro no terminal e rótulo exibido durante o movimento."""

    def test_registra_movimento_aceito(self):
        self.treinar_gesto()
        gesto = self.gesto(40, variacao=0.01)
        with self.assertLogs("libras.movimento.ao_vivo", level="INFO") as registro:
            self.alimentar(self.detector(), [gesto[0]] * 20 + gesto + [gesto[-1]] * 20)
        texto = "\n".join(registro.output)
        self.assertIn("Movimento detectado", texto)
        self.assertIn("ACEITO como J", texto)
        self.assertIn("limiar", texto)

    def test_registra_movimento_curto_ignorado(self):
        self.treinar_gesto()
        base = self.gesto(20)
        sequencia = [base[0]] * 20 + [base[10], base[0], base[10]] + [base[0]] * 20
        with self.assertLogs("libras.movimento.ao_vivo", level="INFO") as registro:
            self.alimentar(self.detector(), sequencia)
        self.assertIn("curto demais", "\n".join(registro.output))

    def test_em_movimento_durante_o_gesto(self):
        detector = self.detector()
        gesto = self.gesto(40)
        self.alimentar(detector, [gesto[0]] * 10 + gesto[:20])
        self.assertTrue(detector.em_movimento)
        self.alimentar(detector, [gesto[19]] * 20, inicio_ms=30 * self.PASSO_MS)
        self.assertFalse(detector.em_movimento)


class AlfabetoFalso:
    """Classificador do alfabeto simulado: responde sempre a mesma letra."""

    def __init__(self, letra="A", pronto=True):
        self.letra = letra
        self.pronto = pronto
        self.chamadas = 0

    def classificar(self, marcos):
        self.chamadas += 1
        return self.letra


class SessaoAoVivoTests(AoVivoBase):
    """Uma sessão por aba: rótulo da tela a partir dos quadros recebidos."""

    def setUp(self):
        super().setUp()
        sessoes.limpar()
        self.addCleanup(sessoes.limpar)

    def quadros(self, vetores, inicio_ms=0):
        return [
            {"timestamp_ms": inicio_ms + i * self.PASSO_MS, "landmarks": v, "mao": "Right" if v else None}
            for i, v in enumerate(vetores)
        ]

    def test_sem_mao_aguarda(self):
        alfabeto = AlfabetoFalso()
        estado = sessoes.SessaoAoVivo().processar(self.quadros([None] * 3), alfabeto)
        self.assertEqual(estado["label"], sessoes.ROTULO_SEM_MAO)
        self.assertFalse(estado["hand_detected"])
        self.assertEqual(alfabeto.chamadas, 0)

    def test_mao_parada_mostra_a_letra_do_ultimo_quadro(self):
        alfabeto = AlfabetoFalso("B")
        parada = [self.gesto(20)[5]] * 10
        estado = sessoes.SessaoAoVivo().processar(self.quadros(parada), alfabeto)
        self.assertEqual(estado["label"], "B")
        self.assertTrue(estado["hand_detected"])
        self.assertTrue(estado["model_ready"])
        self.assertEqual(alfabeto.chamadas, 1)  # só o último quadro do lote

    def test_movimento_reconhecido_fica_na_tela_e_depois_some(self):
        self.treinar_gesto()
        gesto = self.gesto(40, variacao=0.01)
        sessao = sessoes.SessaoAoVivo()
        alfabeto = AlfabetoFalso("I")
        sequencia = [gesto[0]] * 20 + gesto + [gesto[-1]] * 20
        estado = sessao.processar(self.quadros(sequencia), alfabeto)
        self.assertTrue(estado["movement_ready"])
        self.assertEqual(estado["label"], "J")
        self.assertEqual(estado["movement_label"], "J")
        fim = (len(sequencia) - 1) * self.PASSO_MS
        # Pouco depois, ainda J (e não a letra parada do fim do gesto).
        estado = sessao.processar(self.quadros([gesto[-1]], fim + 500), alfabeto)
        self.assertEqual(estado["label"], "J")
        # Passado o tempo de exibição, volta a letra parada.
        depois = fim + sessoes.EXIBICAO_MOVIMENTO_MS + 100
        estado = sessao.processar(self.quadros([gesto[-1]], depois), alfabeto)
        self.assertEqual(estado["label"], "I")
        self.assertIsNone(estado["movement_label"])

    def test_esconde_a_letra_parada_durante_o_movimento(self):
        self.treinar_gesto()
        gesto = self.gesto(40)
        estado = sessoes.SessaoAoVivo().processar(
            self.quadros([gesto[0]] * 10 + gesto[:20]), AlfabetoFalso("I")
        )
        self.assertEqual(estado["label"], sessoes.ROTULO_ANALISANDO)

    def test_sem_modelo_de_movimento_a_letra_parada_continua(self):
        gesto = self.gesto(40)
        estado = sessoes.SessaoAoVivo().processar(
            self.quadros([gesto[0]] * 10 + gesto[:20]), AlfabetoFalso("I")
        )
        self.assertFalse(estado["movement_ready"])
        self.assertEqual(estado["label"], "I")

    def test_quadros_antigos_sao_ignorados(self):
        sessao = sessoes.SessaoAoVivo()
        mao = self.gesto(20)[0]
        sessao.processar(self.quadros([mao] * 3, inicio_ms=10_000), AlfabetoFalso())
        sessao.processar(self.quadros([mao] * 3, inicio_ms=0), AlfabetoFalso())
        self.assertEqual(sessao.ultimo_t, 10_000 + 2 * self.PASSO_MS)

    def test_cada_canal_tem_sua_sessao(self):
        a = sessoes.sessao("canal-aaaa")
        self.assertIs(sessoes.sessao("canal-aaaa"), a)
        self.assertIsNot(sessoes.sessao("canal-bbbb"), a)

    def test_limite_de_sessoes(self):
        for indice in range(sessoes.MAXIMO_SESSOES + 5):
            sessoes.sessao(f"canal-{indice:04d}")
        self.assertEqual(len(sessoes._sessoes), sessoes.MAXIMO_SESSOES)
        self.assertNotIn("canal-0000", sessoes._sessoes)  # a mais antiga saiu

    def test_sessao_ociosa_e_esquecida(self):
        antiga = sessoes.sessao("canal-velho")
        antiga.usada_em -= sessoes.SESSAO_OCIOSA_S + 1
        sessoes.sessao("canal-novo")
        self.assertNotIn("canal-velho", sessoes._sessoes)


class ApiQuadrosTests(AoVivoBase):
    """A página Reconhecer manda os quadros da câmera do navegador."""

    CANAL = "0f8a2c3e-1b2d-4c5e-9f00-112233445566"

    def setUp(self):
        super().setUp()
        sessoes.limpar()
        self.addCleanup(sessoes.limpar)

    def enviar(self, corpo):
        dados = corpo if isinstance(corpo, str) else json.dumps(corpo)
        return self.client.post(reverse("api_quadros"), dados, content_type="application/json")

    def quadros(self, vetores, inicio_ms=0):
        return [
            {"t": inicio_ms + i * self.PASSO_MS, "marcos": v, "mao": "Right" if v else None}
            for i, v in enumerate(vetores)
        ]

    def test_publica_e_responde_o_estado(self):
        self.client.logout()  # o Reconhecer não exige conta
        resposta = self.enviar({"canal": self.CANAL, "quadros": self.quadros([None, None])})
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(
            set(dados), {"label", "movement_label", "hand_detected", "model_ready", "movement_ready",
                         "movement_speed", "movement_limit"}
        )
        self.assertEqual(dados["label"], sessoes.ROTULO_SEM_MAO)
        self.assertFalse(dados["hand_detected"])

    def test_reconhece_movimento_em_varios_lotes(self):
        self.treinar_gesto()
        gesto = self.gesto(40, variacao=0.01)
        sequencia = self.quadros([gesto[0]] * 20 + gesto + [gesto[-1]] * 20)
        rotulos = []
        for inicio in range(0, len(sequencia), 8):  # lotes de 8, como a cada 250 ms
            resposta = self.enviar({"canal": self.CANAL, "quadros": sequencia[inicio:inicio + 8]})
            rotulos.append(resposta.json()["label"])
        self.assertIn("J", rotulos)
        self.assertEqual(rotulos[-1], "J")

    def test_canais_diferentes_nao_se_misturam(self):
        self.treinar_gesto()
        gesto = self.gesto(40, variacao=0.01)
        sequencia = self.quadros([gesto[0]] * 20 + gesto + [gesto[-1]] * 20)
        self.enviar({"canal": self.CANAL, "quadros": sequencia[:90]})
        outro = self.enviar({"canal": "outra-aba-123", "quadros": sequencia[-2:]})
        self.assertIsNone(outro.json()["movement_label"])

    def test_dados_invalidos(self):
        bons = self.quadros([None])
        casos = [
            "não é json",
            {"quadros": bons},
            {"canal": "curto", "quadros": bons},
            {"canal": "canal com espaço!", "quadros": bons},
            {"canal": self.CANAL, "quadros": []},
            {"canal": self.CANAL, "quadros": self.quadros([None] * 91)},
            {"canal": self.CANAL, "quadros": [{"t": 1, "marcos": [0.1] * 10}]},
        ]
        for corpo in casos:
            with self.subTest(corpo=str(corpo)[:60]):
                resposta = self.enviar(corpo)
                self.assertEqual(resposta.status_code, 400)
                self.assertIn("erro", resposta.json())

    def test_exige_post(self):
        self.assertEqual(self.client.get(reverse("api_quadros")).status_code, 405)


class LetraEmendadaNoMovimentoTests(AoVivoBase):
    """Fazer outra letra e emendar no movimento, sem parar antes (A → J)."""

    def emendado(self, gesto):
        from .base import mao_sintetica

        outra = mao_sintetica(1.0, giro=-2.5, tamanho=0.15)  # outra forma de mão, parada
        transicao = [
            [a + (b - a) * k / 8 for a, b in zip(outra, gesto[0])] for k in range(1, 9)
        ]
        return [outra] * 25 + transicao + gesto + [gesto[-1]] * 20

    def test_reconhece_o_gesto_mesmo_sem_parar_antes(self):
        self.treinar_gesto()
        gesto = self.gesto(40, variacao=0.01)
        saidas = self.alimentar(self.detector(), self.emendado(gesto))
        self.assertTrue(saidas)
        _, previsao = saidas[-1]
        self.assertEqual(previsao["previsto"], "J")
        self.assertTrue(previsao["reconhecido"])

    def test_so_trocar_de_letra_nao_vira_movimento(self):
        from .base import mao_sintetica

        self.treinar_gesto()
        a = mao_sintetica(1.0, giro=-2.5, tamanho=0.15)
        b = self.gesto(20)[0]
        troca = [a] * 25 + [[x + (y - x) * k / 8 for x, y in zip(a, b)] for k in range(1, 9)] + [b] * 25
        aceitos = [p for _, p in self.alimentar(self.detector(), troca) if p["reconhecido"]]
        self.assertEqual(aceitos, [])


class TremorDeDedosEscondidosTests(AoVivoBase):
    """M, N, Q: dedos escondidos tremem, mas a mão está parada."""

    def tremendo(self, amplitude, quadros=90):
        import random

        aleatorio = random.Random(11)
        base = self.gesto(20)[0]
        saida = []
        for _ in range(quadros):
            mao = list(base)
            for ponto in range(5, 21):  # dedos; pulso e palma firmes
                mao[ponto * 3] += aleatorio.gauss(0, amplitude)
                mao[ponto * 3 + 1] += aleatorio.gauss(0, amplitude)
            saida.append(mao)
        return saida

    def test_tremor_dos_dedos_nao_vira_movimento(self):
        from libras.movimento.segmentacao import Segmentador

        segmentador = Segmentador()
        viu_movimento = False
        for indice, mao in enumerate(self.tremendo(0.003)):
            segmentador.observar(indice * self.PASSO_MS, mao)
            viu_movimento = viu_movimento or segmentador.em_movimento
        self.assertFalse(viu_movimento)
        self.assertLess(segmentador.velocidade, 4.0)

    def test_movimento_de_verdade_continua_detectado(self):
        from libras.movimento.segmentacao import Segmentador

        gesto = self.gesto(40)
        segmentador = Segmentador()
        segmentos = []
        for indice, mao in enumerate([gesto[0]] * 15 + gesto + [gesto[-1]] * 20):
            fim = segmentador.observar(indice * self.PASSO_MS, mao)
            if fim:
                segmentos.append(fim)
        self.assertEqual(len(segmentos), 1)


class AnalisandoSoDepoisDeUmTempoTests(AoVivoBase):
    def setUp(self):
        super().setUp()
        sessoes.limpar()
        self.addCleanup(sessoes.limpar)

    def test_letra_parada_continua_nos_primeiros_instantes(self):
        self.treinar_gesto()
        gesto = self.gesto(40)
        sessao = sessoes.SessaoAoVivo()
        alfabeto = AlfabetoFalso("M")
        quadros = [
            {"timestamp_ms": i * self.PASSO_MS, "landmarks": v, "mao": "Right"}
            for i, v in enumerate([gesto[0]] * 15 + gesto)
        ]
        rotulos = []
        for quadro in quadros:
            rotulos.append((quadro["timestamp_ms"], sessao.processar([quadro], alfabeto)["label"]))
        inicio = next(t for t, r in rotulos if r == sessoes.ROTULO_ANALISANDO)
        primeiro_movimento = sessao.detector.inicio_movimento_ms or 0
        # Começou a se mover, mas a letra só sai depois do tempo mínimo.
        movendo = [r for t, r in rotulos if t >= 15 * self.PASSO_MS]
        self.assertEqual(movendo[0], "M")
        self.assertGreaterEqual(inicio - 15 * self.PASSO_MS, sessoes.MOSTRAR_ANALISANDO_APOS_MS - 2 * self.PASSO_MS)
        self.assertIsNotNone(primeiro_movimento)

    def test_resposta_traz_a_velocidade_para_o_diagnostico(self):
        estado = sessoes.SessaoAoVivo().processar(
            [{"timestamp_ms": 0, "landmarks": None, "mao": None}], AlfabetoFalso()
        )
        self.assertEqual(estado["movement_speed"], 0.0)
        self.assertEqual(estado["movement_limit"], 6.0)
