from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # O login do /admin/ passa pela tela do site, que tem o limite de
    # tentativas erradas (libras/acesso.py).
    path("admin/login/", RedirectView.as_view(pattern_name="entrar", query_string=True)),
    path("admin/", admin.site.urls),
    path("", include("libras.urls")),
]
