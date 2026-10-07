"""Coleta marcos da mão para treinar o alfabeto estático.

    python manage.py coletar_alfabeto A

Uma janela mostra a câmera com os marcos da mão; S salva uma amostra da
letra, Q sai. As amostras vão para ``dados/amostras_estaticas/landmarks.csv``.
"""
import csv

import cv2
import mediapipe as mp
from django.core.management.base import BaseCommand, CommandError

from .. import saida_segura
from ...caminhos import AMOSTRAS_ESTATICAS
from ...captura.camera import abrir_camera
from ...estatico.features import extrair_features

LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
N_FEATURES = 63  # Só as coordenadas normalizadas; as geométricas são recalculadas no treino.
CABECALHO = ["label"] + [f"f{i}" for i in range(N_FEATURES)]


def validar_letra(texto):
    letra = (texto or "").strip().upper()
    if len(letra) != 1 or letra not in LETRAS:
        raise CommandError("Informe uma única letra entre A e Z.")
    return letra


class Command(BaseCommand):
    help = "Coleta amostras de uma letra do alfabeto estático pela câmera (S salva, Q sai)."

    def add_arguments(self, parser):
        parser.add_argument("letra", nargs="?", help="Letra a coletar (A-Z).")

    def handle(self, *args, **options):
        saida_segura()
        letra = validar_letra(options["letra"] or input("Digite a letra a coletar (A-Z): "))
        AMOSTRAS_ESTATICAS.parent.mkdir(parents=True, exist_ok=True)
        escrever_cabecalho = not AMOSTRAS_ESTATICAS.exists() or AMOSTRAS_ESTATICAS.stat().st_size == 0
        capture = abrir_camera()
        if not capture.isOpened():
            raise CommandError(
                "Não foi possível acessar a webcam. Feche o /reconhecer/ e outros "
                "aplicativos que estejam usando a câmera."
            )
        # Configuração original da coleta do alfabeto, mantida de propósito:
        # alinhá-la ao reconhecedor exigiria recoletar o dataset (decisão
        # pendente do usuário — ver .claude/CONTEXTO.md).
        hands = mp.solutions.hands.Hands(
            static_image_mode=False, max_num_hands=1,
            min_detection_confidence=0.7, min_tracking_confidence=0.7,
        )
        drawing = mp.solutions.drawing_utils
        salvas = 0
        try:
            with AMOSTRAS_ESTATICAS.open("a", newline="", encoding="utf-8") as arquivo:
                writer = csv.writer(arquivo)
                if escrever_cabecalho:
                    writer.writerow(CABECALHO)
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        continue
                    frame = cv2.flip(frame, 1)
                    result = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    if result.multi_hand_landmarks:
                        hand = result.multi_hand_landmarks[0]
                        drawing.draw_landmarks(frame, hand, mp.solutions.hands.HAND_CONNECTIONS)
                        cv2.putText(frame, f"Letra {letra} | S salva | Q sai",
                                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                    (0, 0, 0), 2)
                        key = cv2.waitKey(1) & 0xFF
                        if key == ord("s"):
                            writer.writerow([letra, *extrair_features(hand.landmark)[:N_FEATURES]])
                            arquivo.flush()
                            salvas += 1
                            self.stdout.write(f"Amostra salva para {letra}.")
                        elif key == ord("q"):
                            break
                    cv2.imshow("Coleta Libras", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        finally:
            capture.release()
            hands.close()
            cv2.destroyAllWindows()
        self.stdout.write(self.style.SUCCESS(f"{salvas} amostra(s) de {letra} salvas."))
        if salvas:
            self.stdout.write("Depois de coletar, rode: python manage.py treinar_alfabeto")
