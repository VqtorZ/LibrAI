"""Forms do LibrAI."""
from django import forms

from .models import Sinal


class SinalForm(forms.ModelForm):
    """Cadastro de um novo sinal/gesto.

    A validação acontece no backend: o título é obrigatório, sem espaços
    desnecessários, e a descrição permanece opcional. O tipo default é
    estático; sinais de movimento habilitam a gravação de amostras.
    Exemplos negativos (movimentos a rejeitar) só existem para movimento.
    """

    tipo = forms.ChoiceField(
        label="Tipo do sinal",
        choices=Sinal.Tipo.choices,
        initial=Sinal.Tipo.ESTATICO,
        required=False,
        widget=forms.Select,
    )

    class Meta:
        model = Sinal
        fields = ["titulo", "tipo", "negativo", "descricao"]
        labels = {
            "titulo": "Título do sinal",
            "tipo": "Tipo do sinal",
            "negativo": "Exemplo negativo (o modelo deve rejeitar este movimento)",
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

    def clean_tipo(self):
        return self.cleaned_data.get("tipo") or Sinal.Tipo.ESTATICO

    def clean(self):
        dados = super().clean()
        if dados.get("negativo") and dados.get("tipo") != Sinal.Tipo.MOVIMENTO:
            self.add_error(
                "negativo", "Exemplos negativos precisam ser do tipo movimento."
            )
        return dados
