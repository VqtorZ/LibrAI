from pathlib import Path

from libras.caminhos import AMOSTRAS_MOVIMENTO, BANCO

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "troque-esta-chave-em-producao"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "libras",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "libras.contexto.versao_estaticos",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Todos os dados ficam em dados/ (ver libras/caminhos.py).
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BANCO}}
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# As amostras de movimento (JSON) são os únicos arquivos "de mídia".
MEDIA_ROOT = AMOSTRAS_MOVIMENTO
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Diagnóstico do reconhecimento de movimentos no terminal do runserver.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simples": {"format": "[%(asctime)s] %(message)s", "datefmt": "%H:%M:%S"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simples"}},
    "loggers": {"libras": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
