"""Etapa 4.2 — primeiro treinamento experimental de movimentos."""
from django.core.management.base import BaseCommand, CommandError

from .. import saida_segura
from ... import temporal


class Command(BaseCommand):
    help = "Treina o protótipo experimental de reconhecimento de movimentos (DTW)."

    def handle(self, *args, **options):
        saida_segura()
        self.stdout.write("=== TREINAMENTO DE MOVIMENTOS ===")
        try:
            treino = temporal.treinar()
        except temporal.ErroTemporal as exc:
            raise CommandError(str(exc))
        modelo = treino.modelo

        for classe in modelo["classes"]:
            self.stdout.write("")
            self.stdout.write(f"Sinal: {classe} (id {modelo['sinal_id'][classe]})")
            self.stdout.write(f"Amostras: {modelo['amostras_por_classe'][classe]}")

        if modelo["negativos"]:
            contagem = {}
            for entrada in modelo["negativos"]:
                contagem[entrada["sinal"]] = contagem.get(entrada["sinal"], 0) + 1
            self.stdout.write("")
            self.stdout.write("Exemplos negativos (ensinam a rejeitar):")
            for sinal, quantidade in contagem.items():
                self.stdout.write(f"  {sinal}: {quantidade} amostra(s)")

        if treino.trajetorias:
            resumo = " · ".join(
                f"#{pk}: {brutos}→{processados}"
                for pk, brutos, processados in treino.trajetorias
            )
            self.stdout.write("")
            self.stdout.write("Trajetórias (frames brutos → processados):")
            self.stdout.write(f"  {resumo}")

        if treino.invalidas:
            self.stdout.write("")
            self.stdout.write("Amostras inválidas (ignoradas no treino):")
            for amostra, resultado in treino.invalidas:
                self.stdout.write(
                    f"  amostra #{amostra.pk}: {' · '.join(resultado.problemas)}"
                )

        if treino.excluidas:
            self.stdout.write("")
            self.stdout.write("Classes excluídas (menos de duas amostras):")
            for classe, quantidade in treino.excluidas:
                self.stdout.write(f"  {classe}: {quantidade} amostra(s)")

        self.stdout.write("")
        self.stdout.write("Avaliação leave-one-out (distância DTW intra-classe):")
        for classe in modelo["classes"]:
            for entrada in modelo["loo"][classe]:
                self.stdout.write(
                    f"  {classe}: amostra #{entrada['amostra']} → "
                    f"{entrada['distancia']:.3f} "
                    f"(vizinho mais próximo: #{entrada['vizinho']})"
                )
            distancias = [e["distancia"] for e in modelo["loo"][classe]]
            media = sum(distancias) / len(distancias)
            self.stdout.write(
                f"  {classe}: média {media:.3f} · máxima {max(distancias):.3f}"
            )
            calibracao = modelo["calibracao"][classe]
            if calibracao["negativo_min"] is None:
                origem = f"máx LOO × margem {modelo['margem']}"
            else:
                origem = (
                    f"ajustado pelo negativo mais próximo: "
                    f"{calibracao['negativo_min']:.3f}"
                )
            self.stdout.write(
                f"Limiar de rejeição de {classe}: "
                f"{modelo['limiares'][classe]:.3f} ({origem})"
            )
            if calibracao["sobreposicao"]:
                self.stdout.write(self.style.WARNING(
                    f"AVISO: um exemplo negativo está mais perto de {classe} "
                    "que os próprios exemplos da classe. Revise as gravações "
                    "negativas ou grave mais amostras variadas do sinal."
                ))

        self.stdout.write("")
        self.stdout.write(f"Modelo salvo em {temporal.MODELO_PATH}.")
        self.stdout.write(self.style.SUCCESS("Modelo treinado com sucesso."))

        if len(modelo["classes"]) == 1 and not modelo["negativos"]:
            classe = modelo["classes"][0]
            total = modelo["amostras_por_classe"][classe]
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                f"AVISO: o modelo tem uma única classe ({classe}) com {total} "
                "amostras — isso valida o processamento e a correspondência "
                "ao padrão gravado, mas NÃO prova que diferencia esse "
                "movimento de outros. Colete amostras de outros sinais ou "
                "de exemplos negativos (ex.: J incompleto) e treine "
                "novamente."
            ))
        self.stdout.write(self.style.WARNING(
            "Protótipo experimental (DTW + vizinho mais próximo). "
            "Não use em produção."
        ))
