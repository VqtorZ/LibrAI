"""Captura OpenCV e classificação de letras estáticas de Libras."""
from __future__ import annotations

from pathlib import Path
import threading
import time

import cv2
import mediapipe as mp

from .marcos import marcos_da_mao

try:
    import joblib
except ImportError:
    joblib = None


MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "libras_alphabet.joblib"


# Resolução única da webcam: reconhecimento, coleta do alfabeto e
# gravação de movimentos usam a mesma, para que os marcos da mão (x e y
# normalizados pela largura e pela altura) tenham a mesma proporção.
CAMERA_LARGURA = 960
CAMERA_ALTURA = 540

# Por quanto tempo um movimento reconhecido (ex.: J) fica na tela.
EXIBICAO_MOVIMENTO_S = 2.5
# Exibido enquanto a mão se move: a letra estática seria enganosa
# (o J começa na configuração do I, por exemplo).
ROTULO_ANALISANDO = "Analisando movimento…"
# Uma gravação só começa se a câmera entregou um frame há pouco.
CAMERA_ATIVA_S = 1.5


class GravacaoIndisponivel(Exception):
    """Pedido de gravação que a câmera não pode atender agora."""

# Pontas dos dedos: polegar, indicador, médio, anelar, mindinho.
FINGERTIPS = [4, 8, 12, 16, 20]


def geometric_features(coords):
    """Relevantes p/ distinguir letras parecidas (ex.: U vs V).

    Recebe os 63 valores normalizados (21 marcos x, y, z relativos ao pulso)
    e retorna distâncias entre as pontas dos dedos, que isolam a abertura
    entre os dedos (diferencial U vs V). Scale-invariante.
    """
    points = [coords[i * 3:(i + 1) * 3] for i in range(21)]

    def dist(a, b):
        return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5

    tips = [points[i] for i in FINGERTIPS]
    features = []
    for i in range(len(tips)):
        for j in range(i + 1, len(tips)):
            features.append(dist(tips[i], tips[j]))
    return features


def extract_features(landmarks):
    """Normaliza os 21 marcos em 63 coordenadas relativas ao pulso e
    acrescenta features geométricas para melhor separação U vs V."""
    wrist = landmarks[0]
    values = []
    for point in landmarks:
        values.extend((point.x - wrist.x, point.y - wrist.y, point.z - wrist.z))
    scale = max((abs(value) for value in values), default=1.0) or 1.0
    normalized = [value / scale for value in values]
    return normalized + geometric_features(normalized)


def abrir_camera():
    """Abre a webcam na resolução padrão do projeto."""
    # CAP_DSHOW reduz a demora de inicialização em muitas instalações Windows.
    captura = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    captura.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_LARGURA)
    captura.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_ALTURA)
    return captura


def criar_detector_maos():
    """Detector de mãos do reconhecimento ao vivo (modo vídeo, com rastreio).

    A gravação de movimentos pelo terminal usa o mesmo detector, para
    que as amostras saiam exatamente como o reconhecedor as verá.
    """
    return mp.solutions.hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        model_complexity=0,
        min_detection_confidence=0.65,
        min_tracking_confidence=0.6,
    )


class Camera:
    def __init__(self):
        self._capture = None
        self._lock = threading.Lock()
        self._hands = criar_detector_maos()
        self.model = None
        self.model_error = None
        if joblib is None:
            self.model_error = "Dependência joblib ausente. Instale as dependências do projeto."
        elif MODEL_PATH.exists():
            try:
                self.model = joblib.load(MODEL_PATH)
            except (OSError, ValueError, ImportError) as exc:
                self.model_error = f"Não foi possível carregar o modelo: {exc}"
        self.last_label = "Aguardando mão"
        self.last_error = None
        # Reconhecimento de movimento: criado sob demanda porque depende
        # do Django, e este módulo também é importado pelos scripts de
        # coleta/treino do alfabeto, que rodam sem o Django configurado.
        self._movimento = None
        self.movimento_label = None
        self._movimento_ate = 0.0
        # Gravação de amostras pela página do sinal (mesmo caminho do
        # comando gravar_movimento): os frames entram no gravador aqui.
        self._gravador = None
        self._gravacao_no_limite = False
        self._mao_presente = False
        self._ultimo_frame = 0.0
        self._clientes = 0

    def _open(self):
        if self._capture is None or not self._capture.isOpened():
            self._capture = abrir_camera()
            if not self._capture.isOpened():
                self.last_error = "Não foi possível acessar a webcam. Verifique permissões e se ela está em uso."
                return False
            self.last_error = None
        return True

    def classify(self, landmarks):
        if self.model is None:
            return "Modelo não treinado"
        features = [extract_features(landmarks)]
        try:
            probabilities = self.model.predict_proba(features)[0]
            index = probabilities.argmax()
            confidence = float(probabilities[index])
            label = str(self.model.classes_[index])
        except (AttributeError, IndexError, ValueError) as exc:
            self.model_error = f"Modelo inválido: {exc}"
            return "Modelo inválido"
        return label if confidence >= 0.70 else "Sinal não identificado"

    def _detector_movimento(self):
        if self._movimento is None:
            from .ao_vivo import DetectorMovimento

            self._movimento = DetectorMovimento()
        return self._movimento

    def _observar_movimento(self, result):
        """Alimenta o detector de movimento com o frame atual.

        Um movimento reconhecido (ex.: J) tem prioridade sobre a letra
        estática por ``EXIBICAO_MOVIMENTO_S`` segundos; enquanto a mão
        se move, ``ROTULO_ANALISANDO`` substitui a letra estática.
        """
        landmarks, mao = marcos_da_mao(result)
        agora = time.monotonic()
        detector = self._detector_movimento()
        previsao = detector.observar(int(agora * 1000), landmarks, mao)
        if previsao and previsao["reconhecido"]:
            self.movimento_label = previsao["previsto"]
            self._movimento_ate = agora + EXIBICAO_MOVIMENTO_S
        if agora >= self._movimento_ate:
            self.movimento_label = None
        if self.movimento_label:
            return self.movimento_label
        if detector.em_movimento and detector.pronto:
            return ROTULO_ANALISANDO
        return None

    def _registrar_gravacao(self, landmarks, mao, agora):
        """Acrescenta o frame à gravação em andamento (chamado com o lock)."""
        if self._gravador is None or self._gravacao_no_limite:
            return
        if not self._gravador.adicionar(agora, landmarks, mao):
            # Limite de 30 s: para de acumular; a página salva sozinha.
            self._gravacao_no_limite = True

    def _annotate(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._hands.process(rgb)
        agora = time.monotonic()
        self._ultimo_frame = agora
        self._mao_presente = bool(result.multi_hand_landmarks)
        # O status é exibido pela interface lateral; mantemos a imagem limpa.
        label = "Aguardando mão"
        if result.multi_hand_landmarks:
            hand = result.multi_hand_landmarks[0]
            mp.solutions.drawing_utils.draw_landmarks(
                frame, hand, mp.solutions.hands.HAND_CONNECTIONS
            )
            label = self.classify(hand.landmark)
        if self._gravador is not None:
            # Gravando uma amostra: o reconhecimento de movimento fica em
            # pausa para não interpretar o próprio gesto sendo gravado.
            self._registrar_gravacao(*marcos_da_mao(result), agora)
            self.last_label = label
        else:
            self.last_label = self._observar_movimento(result) or label
        return frame

    # --- gravação de amostras --------------------------------------------
    def iniciar_gravacao(self, sinal):
        """Começa a gravar uma amostra do sinal com a câmera ao vivo."""
        from .gravacao import GravadorMovimento

        with self._lock:
            if self._gravador is not None:
                raise GravacaoIndisponivel("Já existe uma gravação em andamento.")
            if time.monotonic() - self._ultimo_frame > CAMERA_ATIVA_S:
                raise GravacaoIndisponivel(
                    "A câmera não está transmitindo. Aguarde a imagem aparecer."
                )
            if not self._mao_presente:
                raise GravacaoIndisponivel(
                    "Posicione a mão na câmera antes de gravar."
                )
            self._gravador = GravadorMovimento(sinal)
            self._gravacao_no_limite = False
            self._gravador.iniciar(time.monotonic())

    def parar_gravacao(self, sinal):
        """Encerra a gravação do sinal e salva a amostra.

        O salvamento (banco + arquivo) acontece fora do lock, sem
        travar a transmissão da câmera.
        """
        with self._lock:
            gravador = self._gravador
            if gravador is None or gravador.sinal.pk != sinal.pk:
                raise GravacaoIndisponivel("Não há gravação deste sinal em andamento.")
            self._gravador = None
            self._gravacao_no_limite = False
        return gravador.finalizar()

    def descartar_gravacao(self):
        with self._lock:
            self._gravador = None
            self._gravacao_no_limite = False

    def status_gravacao(self):
        gravador = self._gravador
        if gravador is None:
            return {"ativa": False}
        return {
            "ativa": True,
            "sinal_id": gravador.sinal.pk,
            "duracao_ms": gravador.duracao_ms(time.monotonic()),
            "no_limite": self._gravacao_no_limite,
        }

    def frames(self):
        with self._lock:
            self._clientes += 1
        try:
            while True:
                with self._lock:
                    if not self._open():
                        frame = self._error_frame(self.last_error)
                    else:
                        ok, frame = self._capture.read()
                        if not ok:
                            self.last_error = "A webcam não retornou uma imagem."
                            frame = self._error_frame(self.last_error)
                        else:
                            frame = self._annotate(cv2.flip(frame, 1))
                    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
                if ok:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
                time.sleep(0.03)
        finally:
            # O último cliente fechou/abandonou a página: devolve a webcam
            # ao sistema (o próprio _open() reabre na próxima visita),
            # liberando-a para o comando gravar_movimento, e descarta uma
            # gravação que tenha ficado pela metade.
            with self._lock:
                self._clientes -= 1
                if self._clientes <= 0:
                    self._clientes = 0
                    self._gravador = None
                    self._gravacao_no_limite = False
                    if self._capture is not None:
                        self._capture.release()
                        self._capture = None

    @staticmethod
    def _error_frame(message):
        frame = cv2.UMat(CAMERA_ALTURA, CAMERA_LARGURA, cv2.CV_8UC3).get()
        frame[:] = (25, 30, 45)
        cv2.putText(frame, "Webcam indisponivel", (55, 230), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
        cv2.putText(frame, message[:72], (55, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 190, 210), 1)
        return frame

    def status(self):
        error = self.last_error or self.model_error
        detector = self._movimento
        return {
            "label": self.last_label,
            "error": error,
            "model_ready": self.model is not None,
            # O detector só existe depois que a câmera processou frames.
            "movement_ready": detector.pronto if detector is not None else None,
            "movement_label": self.movimento_label,
            "hand_detected": self._mao_presente,
            "recording": self.status_gravacao(),
        }


camera = Camera()
