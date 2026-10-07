"""Câmera do site: desempenho do loop (FPS)."""
import numpy as np
from django.test import TestCase


class DesempenhoCameraTests(TestCase):
    """O loop da câmera do site não pode classificar a letra todo frame."""

    def camera(self):
        from libras.captura import camera as modulo_camera

        camera = modulo_camera.Camera.__new__(modulo_camera.Camera)
        camera._rotulo_estatico = modulo_camera.ROTULO_SEM_MAO
        camera._ultima_classificacao = 0.0
        # Sem conferir o arquivo do modelo (o teste usa um classify falso).
        camera._ultima_conferencia = float("inf")
        camera.chamadas = 0

        def classify(landmarks):
            camera.chamadas += 1
            return "A"

        camera.classify = classify
        return camera

    def test_classifica_no_maximo_a_cada_intervalo(self):
        from libras.captura.camera import INTERVALO_CLASSIFICACAO_S

        camera = self.camera()
        for i in range(30):  # 1 s a 30 fps
            self.assertEqual(camera._classificar_estatico([object()], 100 + i / 30), "A")
        self.assertLessEqual(camera.chamadas, int(1 / INTERVALO_CLASSIFICACAO_S) + 1)
        self.assertGreaterEqual(camera.chamadas, 5)

    def test_mao_nova_e_classificada_na_hora(self):
        from libras.captura.camera import ROTULO_SEM_MAO

        camera = self.camera()
        camera._classificar_estatico([object()], 100.0)
        self.assertEqual(camera._classificar_estatico(None, 100.01), ROTULO_SEM_MAO)
        camera._classificar_estatico([object()], 100.02)
        self.assertEqual(camera.chamadas, 2)

    def test_modelo_estatico_roda_em_um_nucleo(self):
        from libras.captura.camera import camera

        if hasattr(camera.model, "n_jobs"):
            self.assertEqual(camera.model.n_jobs, 1)

    def test_gravacao_nao_classifica(self):
        from libras.captura import camera as modulo_camera

        camera = self.camera()
        camera._hands = type("H", (), {
            "process": lambda self, rgb: type("R", (), {"multi_hand_landmarks": None})()
        })()
        camera._gravador = type("G", (), {"adicionar": lambda self, *a: True})()
        camera._gravacao_no_limite = False
        camera._annotate(np.zeros((54, 96, 3), np.uint8))
        self.assertEqual(camera.last_label, modulo_camera.ROTULO_GRAVANDO)
        self.assertEqual(camera.chamadas, 0)
