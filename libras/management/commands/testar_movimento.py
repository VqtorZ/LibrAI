"""Etapa 4.2 — testa uma amostra temporal contra o modelo DTW."""
from django.core.management.base import BaseCommand, CommandError

from .. import saida_segura
from ... import temporal
from ...models import AmostraMovimento, Sinal


class Command(BaseCommand):
    help = "Testa uma amostra temporal contra o modelo experimental de movimentos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--amostra",
            type=int,
            help="ID da amostra a testar (listamos os IDs quando ausente).",
        )

    def handle(self, *args, **options):
        saida_segura()
        if options["amostra"] is None:
            self._listar()
            return
        try:
            resultado = temporal.testar_amostra(options["amostra"])
        except temporal.ErroTemporal as exc:
            raise CommandError(str(exc))
        self._relatar(resultado)

    def _listar(self):
        amostras = AmostraMovimento.objects.filter(
            ativo=True,
            sinal__ativo=True,
            sinal__tipo=Sinal.Tipo.MOVIMENTO,
        ).order_by("pk")
        if not amostras:
            self.stdout.write(
                "Nenhuma amostra ativa de movimento para testar. "
                "Grave amostras na página do sinal."
            )
            return
        self.stdout.write("Amostras disponíveis:")
        for amostra in amostras:
            self.stdout.write(
                f"  #{amostra.pk} — {amostra.sinal.titulo} "
                f"({amostra.quantidade_frames} frames)"
            )
        self.stdout.write("Use: python manage.py testar_movimento --amostra <id>")

    def _relatar(self, r):
        self.stdout.write("=== TESTE DE MOVIMENTO ===")
        self.stdout.write("")
        self.stdout.write(f"Amostra: #{r['amostra'].pk} (Sinal: {r['esperado']})")
        self.stdout.write(
            f"Frames: {r['frames_brutos']} brutos → "
            f"{r['frames_processados']} processados"
        )
        if r["modo_loo"]:
            self.stdout.write(
                "Modo: leave-one-out (a própria amostra foi excluída dos "
                "templates do modelo)"
            )
        self.stdout.write("")
        self.stdout.write(f"Esperado: {r['esperado']}")
        self.stdout.write(f"Previsto: {r['previsto']}")
        self.stdout.write(
            f"Confiança: {r['confianca'] * 100:.1f}% "
            "(similaridade DTW — não é probabilidade calibrada)"
        )
        self.stdout.write(
            f"Distância DTW: {r['distancia']:.3f} "
            f"(limiar de {r['previsto']}: {r['limiar']:.3f})"
        )
        acertou = r["reconhecido"] and r["previsto"] == r["esperado"]
        simbolo = "✓" if acertou else "✗"
        texto = "RECONHECEU" if acertou else "NÃO RECONHECEU"
        estilo = self.style.SUCCESS if acertou else self.style.ERROR
        self.stdout.write(f"Resultado: {simbolo} {estilo(texto)}")
        if len(r["classes"]) == 1:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "AVISO: o modelo tem uma única classe — o resultado "
                "demonstra correspondência ao padrão gravado, não "
                "discriminação entre sinais."
            ))
