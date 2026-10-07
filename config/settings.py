import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from libras.caminhos import AMOSTRAS_MOVIMENTO, BANCO

from .ambiente import carregar_env, ligado, lista

BASE_DIR = Path(__file__).resolve().parent.parent

# Local: nada a configurar (modo de desenvolvimento). Site no ar: arquivo
# .env (ou o indicado em LIBRAI_ENV, como o .env.publico do publicar.cmd)
# com LIBRAI_PRODUCAO=1, LIBRAI_SECRET_KEY e LIBRAI_HOSTS (ver
# config/ambiente.py e os guias em docs/).
carregar_env(BASE_DIR / os.environ.get("LIBRAI_ENV", ".env"))
PRODUCAO = ligado("LIBRAI_PRODUCAO")
DEBUG = not PRODUCAO

CHAVE_DE_DESENVOLVIMENTO = "so-para-desenvolvimento-local-nunca-em-producao"
SECRET_KEY = os.environ.get("LIBRAI_SECRET_KEY", "" if PRODUCAO else CHAVE_DE_DESENVOLVIMENTO)
if PRODUCAO and len(SECRET_KEY) < 40:
    raise ImproperlyConfigured(
        "Em produção, defina LIBRAI_SECRET_KEY no .env (40+ caracteres aleatórios)."
    )

ALLOWED_HOSTS = lista("LIBRAI_HOSTS") or ["127.0.0.1", "localhost"]
if PRODUCAO and not lista("LIBRAI_HOSTS"):
    raise ImproperlyConfigured("Em produção, defina LIBRAI_HOSTS no .env (ex.: voce.pythonanywhere.com).")
# ".trycloudflare.com" (com ponto) aceita qualquer subdomínio: o link do
# túnel muda a cada vez que ele é ligado.
CSRF_TRUSTED_ORIGINS = [
    f"https://*{host}" if host.startswith(".") else f"https://{host}"
    for host in ALLOWED_HOSTS
    if PRODUCAO
]

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
    # Em produção, entrega os arquivos de static/ (CSS, JS, modelo da mão).
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
# Destino do collectstatic no servidor (o servidor web entrega /static/ daqui).
STATIC_ROOT = BASE_DIR / "staticfiles"
# As amostras de movimento (JSON) são os únicos arquivos "de mídia".
MEDIA_ROOT = AMOSTRAS_MOVIMENTO
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Login (ver libras/acesso.py): a área de Gestos é só para administradores.
LOGIN_URL = "entrar"
LOGIN_REDIRECT_URL = "gestos"
LOGOUT_REDIRECT_URL = "inicio"
# Senhas novas (criar_admin, /admin/): mínimo de 10 caracteres, nada óbvio.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Tentativas de login erradas (ver libras/acesso.py): por e-mail e por IP.
LOGIN_TENTATIVAS_POR_EMAIL = 5
LOGIN_TENTATIVAS_POR_IP = 20
LOGIN_BLOQUEIO_S = 15 * 60
# IP de quem acessa: no PythonAnywhere vem no cabeçalho X-Real-IP; pelo
# túnel da Cloudflare, em CF-Connecting-IP (LIBRAI_IP_CABECALHO). Só é
# confiável porque o servidor escuta apenas o próprio proxy/túnel.
LOGIN_IP_DO_CABECALHO = (
    os.environ.get("LIBRAI_IP_CABECALHO", "HTTP_X_REAL_IP") if PRODUCAO else None
)

# Um processo só no plano grátis do PythonAnywhere: o cache em memória basta.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

if PRODUCAO:
    # Site só por https: cookies nunca trafegam sem criptografia.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = True  # o JS pega o token da página, não do cookie
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    # Sessão de admin expira depois de 12 horas.
    SESSION_COOKIE_AGE = 60 * 60 * 12
    # Arquivos estáticos guardados por 1 hora no navegador (as páginas
    # já pedem versões novas com ?v= quando algo muda).
    WHITENOISE_MAX_AGE = 60 * 60
    # Avisos do "check --deploy" que não se aplicam aqui: o http → https é
    # feito pelo PythonAnywhere ("Force HTTPS" na aba Web), e o site é um
    # subdomínio de pythonanywhere.com (HSTS de subdomínios/preload é para
    # quem tem domínio próprio).
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W008", "security.W021"]

# Diagnóstico do reconhecimento de movimentos no terminal do runserver.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simples": {"format": "[%(asctime)s] %(message)s", "datefmt": "%H:%M:%S"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simples"}},
    "loggers": {"libras": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
