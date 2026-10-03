"""Admin do LibrAI."""
from django.contrib import admin

from .models import AmostraMovimento, Sinal


@admin.register(Sinal)
class SinalAdmin(admin.ModelAdmin):
    list_display = ("titulo", "tipo", "ativo", "criado_em", "atualizado_em")
    list_filter = ("ativo", "tipo")
    list_editable = ("ativo",)
    search_fields = ("titulo", "descricao")
    ordering = ("-criado_em",)
    list_per_page = 25


@admin.register(AmostraMovimento)
class AmostraMovimentoAdmin(admin.ModelAdmin):
    list_display = (
        "sinal",
        "quantidade_frames",
        "duracao_ms",
        "fps",
        "criado_em",
        "ativo",
    )
    list_filter = ("ativo", "sinal__tipo")
    list_editable = ("ativo",)
    search_fields = ("sinal__titulo",)
    list_select_related = ("sinal",)
    ordering = ("-criado_em",)
    list_per_page = 25
    readonly_fields = (
        "sinal",
        "quantidade_frames",
        "duracao_ms",
        "arquivo_dados",
        "fps",
        "quantidade_landmarks",
        "versao_features",
        "criado_em",
        "atualizado_em",
    )
    fields = readonly_fields + ("ativo",)
