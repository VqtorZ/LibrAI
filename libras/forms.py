"""Forms do LibrAI."""
from django import forms

from .models import Sinal


class SinalForm(forms.ModelForm):
    """Cadastro de um novo sinal/gesto.

    A validação acontece no backend: o título é obrigatório, sem espaços
    desnecessários, e a descrição permanece opcional.
    """

    class Meta:
        model = Sinal
        fields = ["titulo", "descricao"]
        labels = {
            "titulo": "Título do sinal",
            "descricao": "Descrição / observação",
        }
        widgets = {
            "titulo": forms.TextInput(
                attrs={"placeholder": "Ex.: Obrigado", "autocomplete": "off"}
            ),
            "descricao": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Opcional: contexto e observações sobre o sinal.",
                }
            ),
        }
        error_messages = {
            "titulo": {"required": "Informe o título do sinal."},
        }

    def clean_titulo(self):
        titulo = self.cleaned_data.get("titulo", "").strip()
        if not titulo:
            raise forms.ValidationError("Informe o título do sinal.")
        return titulo
