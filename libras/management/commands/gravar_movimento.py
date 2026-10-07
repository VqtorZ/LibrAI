"""Grava amostras de um sinal de movimento pela câmera do OpenCV.

Mesmo estilo do comando ``coletar_alfabeto``: uma janela mostra a
câmera com os 21 marcos da mão desenhados, e o teclado controla a
gravação. A captura usa a mesma câmera, resolução e detector do
reconhecimento ao vivo, então as amostras saem como o reconhecedor
as verá.

    python manage.py gravar_movimento J
"""
import time

import cv2
import mediapipe as mp
from django.core.management.base import BaseCommand, CommandError

from .. import saida_segura
from ...captura.camera import abrir_camera, criar_detector_maos
from ...captura.marcos import marcos_da_mao
from ...movimento.amostras import AmostraInvalida
from ...movimento.gravacao import GravadorMovimento, localizar_sinal

TECLA_ESPACO = 32
TECLAS_SAIR = (ord("q"), ord("Q"), 27)  # Q ou ESC
MENSAGEM_S = 3.0
VERDE, VERMELHO, BRANCO, PRETO = (60, 200, 60), (40, 40, 220), (255, 255, 255), (0, 0, 0)


def _texto(frame, texto, linha, cor=BRANCO):
    """Escreve com contorno para ficar legível sobre qualquer fundo."""
    posicao = (20, 36 + linha * 34)
    cv2.putText(frame, texto, posicao, cv2.FONT_HERSHEY_SIMPLEX, 0.75, PRETO, 4)
    cv2.putText(frame, texto, posicao, cv2.FONT_HERSHEY_SIMPLEX, 0.75, cor, 2)


class Command(BaseCommand):
    help = "Grava amostras de um sinal de movimento pela câmera, com os marcos da mão visíveis."

    def add_arguments(self, parser):
        parser.add_argument("sinal", help="Título (ex.: J) ou número do sinal de movimento.")

    def handle(self, *args, **options):
        saida_segura()
        try:
            sinal = localizar_sinal(options["sinal"])
        except AmostraInvalida as exc:
            raise CommandError(str(exc))

        captura = abrir_camera()
        if not captura.isOpened():
            raise CommandError(
                "Não foi possível acessar a webcam. Feche a página /reconhecer/ "
                "e outros aplicativos que estejam usando a câmera."
            )
        hands = criar_detector_maos()
        janela = f"Gravar movimento - {sinal.titulo}"
        gravador = GravadorMovimento(sinal)
        salvas = 0
        mensagem, cor_mensagem, mensagem_ate = "", BRANCO, 0.0

        self.stdout.write(f'Gravando amostras de "{sinal.titulo}" (sinal #{sinal.pk}).')
        self.stdout.write(
            "Faça a configuração inicial com a mão parada, aperte ESPAÇO, faça o "
            "movimento, pare a mão e aperte ESPAÇO de novo. Q ou ESC para sair."
        )

        def avisar(texto, cor=BRANCO):
            nonlocal mensagem, cor_mensagem, mensagem_ate
            mensagem, cor_mensagem = texto, cor
            mensagem_ate = time.monotonic() + MENSAGEM_S
            self.stdout.write(texto)

        def finalizar():
            nonlocal salvas
            try:
                amostra = gravador.finalizar()
            except AmostraInvalida as exc:
                avisar(f"Amostra descartada: {exc}", VERMELHO)
                return
            salvas += 1
            avisar(
                f"Amostra #{amostra.pk} salva ({amostra.quantidade_frames} frames, "
                f"{amostra.duracao_segundos} s).",
                VERDE,
            )

        falhas = 0
        try:
            while True:
                ok, frame = captura.read()
                if not ok:
                    falhas += 1
                    if falhas > 100:
                        raise CommandError("A webcam parou de enviar imagens.")
                    continue
                falhas = 0
                frame = cv2.flip(frame, 1)
                resultado = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                landmarks, mao = marcos_da_mao(resultado)
                agora = time.monotonic()
                if resultado.multi_hand_landmarks:
                    mp.solutions.drawing_utils.draw_landmarks(
                        frame, resultado.multi_hand_landmarks[0],
                        mp.solutions.hands.HAND_CONNECTIONS,
                    )
                if gravador.gravando and not gravador.adicionar(agora, landmarks, mao):
                    finalizar()  # limite de 30 s atingido

                _texto(frame, f"Sinal {sinal.titulo} | ESPACO grava/para | Q sai | salvas: {salvas}", 0)
                if gravador.gravando:
                    _texto(frame, f"GRAVANDO {gravador.duracao_ms(agora) / 1000:.1f} s", 1, VERMELHO)
                elif landmarks is not None:
                    _texto(frame, "Mao detectada - pronto para gravar", 1, VERDE)
                else:
                    _texto(frame, "Sem mao - posicione a mao na camera", 1, VERMELHO)
                if agora < mensagem_ate:
                    # A janela do OpenCV não desenha acentos.
                    _texto(frame, mensagem.encode("ascii", "ignore").decode(), 2, cor_mensagem)
                cv2.imshow(janela, frame)

                tecla = cv2.waitKey(1) & 0xFF
                if tecla == TECLA_ESPACO:
                    if gravador.gravando:
                        finalizar()
                    elif landmarks is None:
                        avisar("Posicione a mão na câmera antes de gravar.", VERMELHO)
                    else:
                        gravador.iniciar(agora)
                elif tecla in TECLAS_SAIR:
                    break
                if cv2.getWindowProperty(janela, cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            if gravador.gravando:
                gravador.descartar()
                self.stdout.write("Gravação em andamento descartada.")
            captura.release()
            hands.close()
            cv2.destroyAllWindows()

        self.stdout.write(self.style.SUCCESS(f"{salvas} amostra(s) salva(s) para {sinal.titulo}."))
        if salvas:
            self.stdout.write("Depois de gravar, rode: python manage.py treinar_movimentos")
