"""Treina o classificador do alfabeto estático.

    python manage.py treinar_alfabeto
"""
from django.core.management.base import BaseCommand, CommandError

from .. import saida_segura
from ...caminhos import MODELO_ALFABETO
from ...estatico.treino import ErroTreino, treinar


class Command(BaseCommand):
    help = "Treina o classificador do alfabeto estático a partir das amostras coletadas."

    def handle(self, *args, **options):
        saida_segura()
        try:
            relatorio = treinar()
        except ErroTreino as exc:
            raise CommandError(str(exc))
        self.stdout.write(relatorio)
        self.stdout.write(self.style.SUCCESS(f"Modelo salvo em {MODELO_ALFABETO}."))
        self.stdout.write("Reinicie o runserver para a câmera carregar o modelo novo.")
