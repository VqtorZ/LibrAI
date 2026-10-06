"""Etapa 4.2/4.3 — testa uma amostra temporal ou um arquivo externo.

``--amostra`` testa uma gravação do banco (modo leave-one-out quando
ela participou do treino). ``--arquivo`` testa um JSON externo no
formato das amostras — a entrada controlada de não-J da Etapa 4.3:
o esperado é REJEITADO quando o movimento não casa com nenhuma
classe do modelo.
"""
from django.core.management.base import BaseCommand, CommandError

from .. import saida_segura
from ... import temporal
from ...models import AmostraMovimento, Sinal


class Command(BaseCommand):
    help = "Testa uma amostra temporal ou um arquivo externo contra o modelo de movimentos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--amostra",
            type=int,
            help="ID da amostra gravada a testar.",
        )
        parser.add_argument(
            "--arquivo",
            type=str,
            help="Caminho de um JSON externo (formato de amostra) a testar.",
        )

    def handle(self, *args, **options):
        saida_segura()
        if options["amostra"] is not None and options["arquivo"]:
            raise CommandError("Use --amostra ou --arquivo, não ambos.")
        if options["arquivo"]:
            try:
                resultado = temporal.testar_arquivo(options["arquivo"])
            except temporal.ErroTemporal as exc:
                raise CommandError(str(exc))
            self._relatar_arquivo(resultado)
            return
        if options["amostra"] is not None:
            try:
                resultado = temporal.testar_amostra(options["amostra"])
            except temporal.ErroTemporal as exc:
                raise CommandError(str(exc))
            self._relatar_amostra(resultado)
            return
        self._listar()

    def _listar(self):
        amostras = AmostraMovimento.objects.filter(
            ativo=True,
            sinal__ativo=True,
            sinal__tipo=Sinal.Tipo.MOVIMENTO,
        ).order_by("pk")
        self.stdout.write("Modos de teste:")
        self.stdout.write(
            "  --amostra <id>  testa uma gravação do banco (leave-one-out "
            "quando participou do treino)"
        )
        self.stdout.write(
            "  --arquivo <caminho>  testa um JSON externo (entrada não-J "
            "para o teste de rejeição)"
        )
        if amostras:
            self.stdout.write("")
            self.stdout.write("Amostras disponíveis:")
            for amostra in amostras:
                self.stdout.write(
                    f"  #{amostra.pk} — {amostra.sinal.titulo} "
                    f"({amostra.quantidade_frames} frames)"
                )

    def _relatar_amostra(self, r):
        self.stdout.write("=== TESTE DE MOVIMENTO ===")
        self.stdout.write("")
        tipo = " — exemplo negativo" if r["negativo"] else ""
        self.stdout.write(f"Amostra: #{r['amostra'].pk} (Sinal: {r['esperado']}{tipo})")
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
        esperado = "REJEITADO" if r["negativo"] else r["esperado"]
        previsto = r["previsto"] if r["reconhecido"] else "REJEITADO"
        self.stdout.write(f"Esperado: {esperado}")
        self.stdout.write(f"Previsto: {previsto}")
        self.stdout.write(
            f"Confiança: {r['confianca'] * 100:.1f}% "
            "(similaridade DTW — não é probabilidade calibrada)"
        )
        self.stdout.write(
            f"Distância DTW: {r['distancia']:.3f} "
            f"(limiar de {r['previsto']}: {r['limiar']:.3f})"
        )
        self._relatar_negativo(r)
        if r["negativo"]:
            acertou = not r["reconhecido"]
            texto = "REJEITOU" if acertou else "ACEITOU — FALSO POSITIVO"
        else:
            acertou = r["reconhecido"] and r["previsto"] == r["esperado"]
            texto = "RECONHECEU" if acertou else "NÃO RECONHECEU"
        simbolo = "✓" if acertou else "✗"
        estilo = self.style.SUCCESS if acertou else self.style.ERROR
        self.stdout.write(f"Resultado: {simbolo} {estilo(texto)}")
        if len(r["classes"]) == 1 and not r["negativo_mais_proximo"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "AVISO: o modelo tem uma única classe — o resultado "
                "demonstra correspondência ao padrão gravado, não "
                "discriminação entre sinais."
            ))

    def _relatar_negativo(self, r):
        negativo = r["negativo_mais_proximo"]
        if negativo is None:
            return
        self.stdout.write(
            f"Negativo mais próximo: {negativo['sinal']} "
            f"(amostra #{negativo['amostra']}, distância {negativo['distancia']:.3f})"
        )
        if r["motivo_rejeicao"] == "negativo":
            self.stdout.write(
                "Rejeitado porque um exemplo negativo é mais parecido que "
                f"qualquer amostra de {r['previsto']}."
            )

    def _relatar_arquivo(self, r):
        self.stdout.write("=== TESTE DE MOVIMENTO (ARQUIVO EXTERNO) ===")
        self.stdout.write("")
        self.stdout.write(f"Arquivo: {r['arquivo']}")
        self.stdout.write(
            f"Frames: {r['frames_brutos']} brutos → "
            f"{r['frames_processados']} processados"
        )
        self.stdout.write("")
        self.stdout.write(f"Esperado: {r['esperado']}")
        previsto = r["previsto"] if r["reconhecido"] else "REJEITADO"
        self.stdout.write(f"Previsto: {previsto}")
        self.stdout.write(
            f"Confiança: {r['confianca'] * 100:.1f}% "
            "(similaridade DTW — não é probabilidade calibrada)"
        )
        self.stdout.write(
            f"Distância DTW: {r['distancia']:.3f} "
            f"(limiar de {r['previsto']}: {r['limiar']:.3f})"
        )
        self._relatar_negativo(r)
        if r["reconhecido"]:
            self.stdout.write(self.style.ERROR(
                f"Resultado: ✗ ACEITOU — FALSO POSITIVO: a entrada não-J "
                f"foi classificada como {r['previsto']}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "Resultado: ✓ REJEITOU (o movimento não casa com nenhuma "
                "classe do modelo)"
            ))
        if len(r["classes"]) == 1:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "AVISO: o modelo tem uma única classe — a rejeição de não-J "
                "depende inteiramente do limiar DTW; não há outras classes "
                "para contraste."
            ))
