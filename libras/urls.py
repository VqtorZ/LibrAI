from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .acesso import FormularioEntrar

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("reconhecer/", views.reconhecer, name="reconhecer"),
    path(
        "entrar/",
        auth_views.LoginView.as_view(
            template_name="libras/entrar.html",
            authentication_form=FormularioEntrar,
            redirect_authenticated_user=True,
        ),
        name="entrar",
    ),
    path("sair/", auth_views.LogoutView.as_view(), name="sair"),
    path("api/quadros/", views.api_quadros, name="api_quadros"),
    path("gestos/", views.gestos, name="gestos"),
    path("gestos/novo/", views.gesto_novo, name="gesto_novo"),
    path("gestos/treinar/", views.treinar_movimentos, name="treinar_movimentos"),
    path("gestos/alfabeto/", views.alfabeto_gravar, name="alfabeto_gravar"),
    path(
        "gestos/alfabeto/amostras/",
        views.alfabeto_amostra_salvar,
        name="alfabeto_amostra_salvar",
    ),
    path(
        "gestos/alfabeto/desfazer/",
        views.alfabeto_amostra_desfazer,
        name="alfabeto_amostra_desfazer",
    ),
    path("gestos/alfabeto/treinar/", views.treinar_alfabeto, name="treinar_alfabeto"),
    path("gestos/<int:sinal_id>/", views.gesto_detalhe, name="gesto_detalhe"),
    path("gestos/<int:sinal_id>/gravar/", views.gesto_gravar, name="gesto_gravar"),
    path("gestos/<int:sinal_id>/excluir/", views.gesto_excluir, name="gesto_excluir"),
    path(
        "gestos/<int:sinal_id>/amostras/",
        views.gesto_amostra_gravar,
        name="gesto_amostra_gravar",
    ),
    path(
        "gestos/<int:sinal_id>/amostras/<int:amostra_id>/apagar/",
        views.gesto_amostra_apagar,
        name="gesto_amostra_apagar",
    ),
]
