"""Models do LibrAI."""
from django.db import models


class Sinal(models.Model):
    """Sinal ou gesto cadastrado colaborativamente no LibrAI.

    Representa entradas genéricas do vocabulário (letras, palavras ou nomes),
    sem regras específicas de Libras — o cadastro é livre.
    """

    titulo = models.CharField("título", max_length=120)
    descricao = models.TextField("descrição", blank=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ("-criado_em",)
        verbose_name = "sinal"
        verbose_name_plural = "sinais"

    def __str__(self):
        return self.titulo
