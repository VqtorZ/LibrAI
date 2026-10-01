"""Admin do LibrAI."""
from django.contrib import admin

from .models import Sinal


@admin.register(Sinal)
class SinalAdmin(admin.ModelAdmin):
    list_display = ("titulo", "ativo", "criado_em", "atualizado_em")
    list_filter = ("ativo",)
    list_editable = ("ativo",)
    search_fields = ("titulo", "descricao")
    ordering = ("-criado_em",)
    list_per_page = 25
