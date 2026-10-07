"""Acesso ao LibrAI: login pelo e-mail e páginas só para administradores.

* Livre para todos: a home e o Reconhecer (o público usa sem conta).
* Só administradores (``is_staff``): a área de Gestos — cadastrar,
  gravar, apagar, excluir e treinar.
* Admin master (``is_superuser``): também gerencia os usuários em /admin/.

Cada conta usa o e-mail como nome de usuário (em minúsculas). Contas
novas: ``python manage.py criar_admin <email>``. As senhas nunca ficam
no código: só no banco, criptografadas pelo Django.
"""
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm


def eh_admin(usuario):
    return usuario.is_active and usuario.is_staff


# Visitante (ou conta sem permissão) é levado à tela de login e, depois
# de entrar, volta para a página que tentou abrir.
apenas_admin = user_passes_test(eh_admin, login_url="entrar")


class FormularioEntrar(AuthenticationForm):
    """Login pelo e-mail, com mensagens em português."""

    username = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={
            "autofocus": True,
            "autocomplete": "email",
            "placeholder": "voce@exemplo.com",
        }),
    )
    password = forms.CharField(
        label="Senha",
        strip=False,
        widget=forms.PasswordInput(attrs={
            "autocomplete": "current-password",
            "placeholder": "Sua senha",
        }),
    )
    error_messages = {
        "invalid_login": "E-mail ou senha incorretos. Confira e tente de novo.",
        "inactive": "Esta conta está desativada.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError(
                "Esta conta não tem acesso de administrador.", code="sem_acesso"
            )
