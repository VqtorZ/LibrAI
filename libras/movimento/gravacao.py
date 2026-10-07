"""Gravação de amostras de movimento pela câmera do OpenCV.

Lógica do comando ``gravar_movimento``, separada da janela para poder
ser testada sem webcam. A captura usa a mesma câmera, resolução e
detector de mãos do reconhecimento ao vivo (``libras.captura.camera``), então
as amostras saem exatamente como o reconhecedor as verá — o mesmo
princípio que faz a coleta do alfabeto estático funcionar.
"""
from __future__ import annotations

from ..models import Sinal
from .amostras import DURACAO_MAX_MS, AmostraInvalida, salvar_amostra

ORIGEM = "opencv"
# A câmera do OpenCV roda a ~30 fps: 30 s cabem com folga.
FRAMES_MAX = 1200


def localizar_sinal(identificador):
    """Sinal de movimento ativo pelo id ou pelo título (sem diferenciar caixa).

    Levanta ``AmostraInvalida`` com uma mensagem orientando o usuário
    quando o sinal não existe, é ambíguo ou não é de movimento.
    """
    sinais = Sinal.objects.filter(ativo=True, tipo=Sinal.Tipo.MOVIMENTO)
    texto = str(identificador).strip()
    if texto.isdigit():
        encontrados = list(sinais.filter(pk=int(texto)))
    else:
        encontrados = list(sinais.filter(titulo__iexact=texto))
    if len(encontrados) == 1:
        return encontrados[0]
    if len(encontrados) > 1:
        opcoes = ", ".join(f"#{s.pk} {s.titulo}" for s in encontrados)
        raise AmostraInvalida(
            f'Mais de um sinal chamado "{texto}" ({opcoes}). Use o número do sinal.'
        )
    disponiveis = ", ".join(
        f"{s.titulo} (#{s.pk})" for s in sinais.order_by("titulo")
    ) or "nenhum"
    raise AmostraInvalida(
        f'Sinal de movimento "{texto}" não encontrado. Disponíveis: '
        f"{disponiveis}. Cadastre novos sinais em /gestos/novo/."
    )


class GravadorMovimento:
    """Acumula os frames de uma gravação e salva a amostra no fim."""

    def __init__(self, sinal):
        self.sinal = sinal
        self.frames = []
        self._inicio = None

    @property
    def gravando(self):
        return self._inicio is not None

    def duracao_ms(self, agora_s):
        return int((agora_s - self._inicio) * 1000) if self.gravando else 0

    def iniciar(self, agora_s):
        self.frames = []
        self._inicio = agora_s

    def adicionar(self, agora_s, landmarks, mao):
        """Registra um frame; False quando o limite de duração foi atingido."""
        if not self.gravando:
            return False
        decorrido = self.duracao_ms(agora_s)
        if decorrido > DURACAO_MAX_MS or len(self.frames) >= FRAMES_MAX:
            return False
        self.frames.append(
            {"timestamp_ms": decorrido, "landmarks": landmarks, "mao": mao}
        )
        return True

    def descartar(self):
        self.frames = []
        self._inicio = None

    def finalizar(self):
        """Encerra a gravação e salva a amostra (``AmostraInvalida`` se ruim)."""
        frames, self.frames, self._inicio = self.frames, [], None
        if not frames:
            raise AmostraInvalida("Nenhum frame gravado.")
        return salvar_amostra(self.sinal, frames, origem=ORIGEM)
