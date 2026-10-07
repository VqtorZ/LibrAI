"""Reconhecimento de movimento ao vivo e diagnóstico no terminal."""
from django.urls import reverse

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

    def test_status_informa_movimento(self):
        response = self.client.get(reverse("status"))
        payload = response.json()
        self.assertIn("movement_ready", payload)
        self.assertIn("movement_label", payload)


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

    def camera_com(self, em_movimento, pronto=True, previsao=None):
        from libras.captura import camera as modulo_camera

        detector = type("D", (), {
            "observar": lambda self, *a: previsao,
            "em_movimento": em_movimento,
            "pronto": pronto,
        })()
        camera = modulo_camera.Camera.__new__(modulo_camera.Camera)
        camera._movimento = detector
        camera.movimento_label = None
        camera._movimento_ate = 0.0
        sem_mao = type("R", (), {"multi_hand_landmarks": None})()
        return camera._observar_movimento(sem_mao)

    def test_camera_esconde_letra_estatica_durante_movimento(self):
        from libras.captura.camera import ROTULO_ANALISANDO

        self.assertEqual(self.camera_com(em_movimento=True), ROTULO_ANALISANDO)
        self.assertIsNone(self.camera_com(em_movimento=False))
        # Sem modelo de movimento treinado, a letra estática continua.
        self.assertIsNone(self.camera_com(em_movimento=True, pronto=False))

    def test_camera_exibe_movimento_reconhecido(self):
        previsao = {"reconhecido": True, "previsto": "J"}
        self.assertEqual(self.camera_com(em_movimento=False, previsao=previsao), "J")
