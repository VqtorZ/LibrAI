"""Models do LibrAI."""
from django.db import models


class Sinal(models.Model):
    """Sinal ou gesto cadastrado colaborativamente no LibrAI.

    Representa entradas genéricas do vocabulário (letras, palavras ou nomes),
    sem regras específicas de Libras — o cadastro é livre. Sinais do tipo
    MOVIMENTO aceitam amostras temporais gravadas pela câmera.
    """

    class Tipo(models.TextChoices):
        ESTATICO = "ESTATICO", "Estático"
        MOVIMENTO = "MOVIMENTO", "Movimento"

    titulo = models.CharField("título", max_length=120)
    tipo = models.CharField(
        "tipo", max_length=20, choices=Tipo.choices, default=Tipo.ESTATICO
    )
    descricao = models.TextField("descrição", blank=True)
    negativo = models.BooleanField(
        "exemplo negativo",
        default=False,
        help_text=(
            "Movimento que NÃO deve ser reconhecido (ex.: J incompleto, "
            "I parado). Suas amostras ensinam o modelo a rejeitar."
        ),
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ("-criado_em",)
        verbose_name = "sinal"
        verbose_name_plural = "sinais"

    def __str__(self):
        return self.titulo


class AmostraMovimento(models.Model):
    """Amostra temporal gravada para um sinal do tipo MOVIMENTO.

    A sequência de landmarks fica em um arquivo JSON em
    ``movimentos/<sinal_id>/<amostra_id>.json`` dentro de ``MEDIA_ROOT``;
    o banco guarda apenas os metadados e a referência ao arquivo.
    """

    sinal = models.ForeignKey(
        Sinal,
        on_delete=models.CASCADE,
        related_name="amostras",
        verbose_name="sinal",
    )
    quantidade_frames = models.PositiveIntegerField("quantidade de frames")
    duracao_ms = models.PositiveIntegerField("duração (ms)")
    arquivo_dados = models.CharField("arquivo de dados", max_length=255)
    fps = models.FloatField("fps", default=0.0)
    quantidade_landmarks = models.PositiveIntegerField(
        "landmarks por frame", default=21
    )
    versao_features = models.PositiveIntegerField("versão das features", default=1)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ("-criado_em",)
        verbose_name = "amostra de movimento"
        verbose_name_plural = "amostras de movimento"

    def __str__(self):
        return f"{self.sinal.titulo} — amostra #{self.pk} ({self.quantidade_frames} frames)"

    @property
    def duracao_segundos(self):
        return round(self.duracao_ms / 1000, 1)
