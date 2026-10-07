"""Coleta marcos da mão para treinar o alfabeto estático de Libras."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import mediapipe as mp

# Permite executar este arquivo diretamente a partir da raiz do projeto.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from libras.caminhos import AMOSTRAS_ESTATICAS
from libras.vision import abrir_camera, extract_features


LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
OUTPUT = AMOSTRAS_ESTATICAS
N_FEATURES = 63  # Só as coordenadas normalizadas; as geométricas são recalculadas no treino.
HEADER = ["label"] + [f"f{i}" for i in range(N_FEATURES)]


def choose_letter():
    while True:
        letter = input("Digite a letra a coletar (A-Z): ").strip().upper()
        if letter in LETTERS:
            return letter
        print("Informe uma única letra entre A e Z.")


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUTPUT.exists() or OUTPUT.stat().st_size == 0
    letter = choose_letter()
    # Mesma resolução do reconhecimento (antes ficava no padrão da webcam,
    # geralmente 640x480, o que distorcia a proporção dos marcos).
    capture = abrir_camera()
    if not capture.isOpened():
        raise RuntimeError("Não foi possível acessar a webcam.")

    hands = mp.solutions.hands.Hands(
        static_image_mode=False, max_num_hands=1,
        min_detection_confidence=0.7, min_tracking_confidence=0.7,
    )
    drawing = mp.solutions.drawing_utils
    try:
        with OUTPUT.open("a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            if write_header:
                writer.writerow(HEADER)
            while True:
                ok, frame = capture.read()
                if not ok:
                    continue
                frame = cv2.flip(frame, 1)
                result = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                if result.multi_hand_landmarks:
                    hand = result.multi_hand_landmarks[0]
                    drawing.draw_landmarks(frame, hand, mp.solutions.hands.HAND_CONNECTIONS)
                    cv2.putText(frame, f"Letra {letter} | S salva | Q sai",
                                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                (0, 0, 0), 2)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("s"):
                        writer.writerow([letter, *extract_features(hand.landmark)[:N_FEATURES]])
                        file.flush()
                        print(f"Amostra salva para {letter}.")
                    elif key == ord("q"):
                        break
                cv2.imshow("Coleta Libras", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        capture.release()
        hands.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
