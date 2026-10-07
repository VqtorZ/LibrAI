"""Cria (ou atualiza) uma conta de administrador do LibrAI.

    python manage.py criar_admin pessoa@exemplo.com --nome Pessoa
    python manage.py criar_admin voce@exemplo.com --nome Você --master

A senha é pedida no terminal (não aparece na tela) e nunca é passada
pela linha de comando. --master dá acesso total, inclusive ao
gerenciamento de usuários em /admin/.
"""
import getpass

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from .. import saida_segura


class Command(BaseCommand):
    help = "Cria ou atualiza uma conta de administrador (login pelo e-mail)."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--nome", default="", help="Nome exibido no site.")
        parser.add_argument("--master", action="store_true", help="Acesso total (gerencia usuários).")

    def handle(self, *args, **options):
        saida_segura()
        email = options["email"].strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError(f"E-mail inválido: {email}")
        senha = getpass.getpass("Senha: ")
        if not senha or senha != getpass.getpass("Repita a senha: "):
            raise CommandError("As senhas não conferem (ou estão vazias).")
        usuario, criado = User.objects.get_or_create(username=email, defaults={"email": email})
        usuario.email = email
        if options["nome"]:
            usuario.first_name = options["nome"]
        usuario.is_active = True
        usuario.is_staff = True
        usuario.is_superuser = options["master"]
        usuario.set_password(senha)
        usuario.save()
        tipo = "master" if options["master"] else "administrador"
        acao = "criada" if criado else "atualizada"
        self.stdout.write(self.style.SUCCESS(f"Conta {tipo} {acao}: {email}"))
