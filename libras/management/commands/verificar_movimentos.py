"""Etapa 4.1 — verificador de amostras temporais.

Lê as amostras gravadas em ``dados/amostras_movimento/`` e confere a
estrutura dos JSONs, a consistência com os metadados do banco e a
presença de landmarks suficientes. Diagnóstico apenas: não treina,
não classifica e não promete reconhecimento — apenas declara se a
coleta está pronta para uma futura etapa de treinamento.
"""
from django.core.management.base import BaseCommand

from .. import saida_segura
from ...models import Sinal
from ...verificacao import (
    LANDMARKS_POR_MAO,
    VALORES_POR_FRAME,
    resumir,
    verificar_amostra,
)


class Command(BaseCommand):
    help = "Verifica a integridade estrutural das amostras temporais gravadas."

    def handle(self, *args, **options):
        saida_segura()
        sinais = (
            Sinal.objects.filter(
                tipo=Sinal.Tipo.MOVIMENTO,
                ativo=True,
                amostras__ativo=True,
            )
            .distinct()
            .order_by("pk")
        )
        verificou = False
        for sinal in sinais:
            verificou = True
            self._relatar_sinal(sinal)
        if not verificou:
            self.stdout.write(
                self.style.WARNING("Nenhum sinal de movimento com amostras ativas.")
            )

    def _relatar_sinal(self, sinal):
        resultados = [
            (amostra, verificar_amostra(amostra))
            for amostra in sinal.amostras.filter(ativo=True)
        ]
        self.stdout.write(f"\nSINAL #{sinal.pk} — {sinal.titulo}")
        self.stdout.write(f"Amostras: {len(resultados)}")
        for amostra, resultado in resultados:
            self._relatar_amostra(amostra, resultado)
        self._relatar_resumo(sinal, resumir([r for _, r in resultados]))

    def _relatar_amostra(self, amostra, resultado):
        self.stdout.write(f"\nAMOSTRA #{amostra.pk}")
        if not resultado.ok:
            self.stdout.write(f"  Status: {self.style.ERROR('INVÁLIDA')}")
            self.stdout.write("  Problemas:")
            for problema in resultado.problemas:
                self.stdout.write(f"    - {problema}")
            return
        self.stdout.write(f"  Frames: {resultado.total_frames}")
        self.stdout.write(f"  Frames válidos: {resultado.frames_validos}")
        self.stdout.write(
            f"  Frames sem landmarks: {resultado.frames_sem_landmarks}"
        )
        self.stdout.write(f"  Taxa válida: {resultado.taxa_validos:.2f}%")
        self.stdout.write(
            f"  Duração: {resultado.duracao_ms} ms ({resultado.duracao_segundos:.2f} s)"
        )
        self.stdout.write(f"  FPS: {resultado.fps:g}")
        self.stdout.write(f"  Landmarks/frame: {LANDMARKS_POR_MAO}")
        self.stdout.write(f"  Valores/frame: {VALORES_POR_FRAME}")
        self.stdout.write(f"  Status: {self.style.SUCCESS('OK')}")

    def _relatar_resumo(self, sinal, resumo):
        status = (
            self.style.SUCCESS("PRONTO PARA TREINAMENTO")
            if resumo.pronto
            else self.style.ERROR("REVISAR AMOSTRAS")
        )
        self.stdout.write("\nRESUMO")
        self.stdout.write(f"Sinal: {sinal.titulo}")
        self.stdout.write(f"Amostras: {resumo.amostras}")
        self.stdout.write(f"Amostras válidas: {resumo.validas}")
        self.stdout.write(f"Amostras inválidas: {resumo.invalidas}")
        self.stdout.write(f"Frames totais: {resumo.frames_totais}")
        self.stdout.write(f"Frames válidos: {resumo.frames_validos}")
        self.stdout.write(f"Taxa média de frames válidos: {resumo.taxa_media:.2f}%")
        self.stdout.write(f"Duração média: {resumo.duracao_media_s:.2f} s")
        self.stdout.write(f"Status do dataset: {status}")
