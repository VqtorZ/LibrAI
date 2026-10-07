"""Acesso ao LibrAI: login pelo e-mail e páginas só para administradores.

* Livre para todos: a home e o Reconhecer (o público usa sem conta).
* Só administradores (``is_staff``): a área de Gestos — cadastrar,
  gravar, apagar, excluir e treinar.
* Admin master (``is_superuser``): também gerencia os usuários em /admin/.

Cada conta usa o e-mail como nome de usuário (em minúsculas). Contas
novas: ``python manage.py criar_admin <email>``. As senhas nunca ficam
no código: só no banco, criptografadas pelo Django.

Com o site no ar, tentativas de adivinhar a senha são barradas: depois de
5 erros seguidos no mesmo e-mail (ou 20 vindos do mesmo IP), o login fica
bloqueado por 15 minutos (``LOGIN_*`` em ``config/settings.py``).
"""
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache


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
        "bloqueado": "Muitas tentativas erradas. Espere 15 minutos e tente de novo.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()

    def _chaves(self):
        """Contadores de erro deste e-mail e deste IP, com os limites de cada um."""
        chaves = []
        email = self.cleaned_data.get("username")
        if email:
            chaves.append((f"login-erros:email:{email}", settings.LOGIN_TENTATIVAS_POR_EMAIL))
        ip = None
        if self.request is not None:
            cabecalho = settings.LOGIN_IP_DO_CABECALHO
            ip = (cabecalho and self.request.META.get(cabecalho)) or self.request.META.get("REMOTE_ADDR")
        if ip:
            chaves.append((f"login-erros:ip:{ip}", settings.LOGIN_TENTATIVAS_POR_IP))
        return chaves

    def clean(self):
        chaves = self._chaves()
        if any(cache.get(chave, 0) >= limite for chave, limite in chaves):
            # Bloqueado: nem confere a senha (não dá pista se estaria certa).
            raise forms.ValidationError(self.error_messages["bloqueado"], code="bloqueado")
        try:
            dados = super().clean()
        except forms.ValidationError:
            for chave, _ in chaves:
                # A janela conta a partir do primeiro erro.
                cache.add(chave, 0, settings.LOGIN_BLOQUEIO_S)
                try:
                    cache.incr(chave)
                except ValueError:  # expirou entre o add e o incr
                    cache.set(chave, 1, settings.LOGIN_BLOQUEIO_S)
            raise
        for chave, _ in chaves:
            if chave.startswith("login-erros:email:"):
                cache.delete(chave)  # acertou: zera os erros deste e-mail
        return dados

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError(
                "Esta conta não tem acesso de administrador.", code="sem_acesso"
            )
