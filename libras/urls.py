from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("reconhecer/", views.recognizer, name="recognizer"),
    path("video/", views.video_feed, name="video_feed"),
    path("api/status/", views.status, name="status"),
    path("gestos/", views.gestos, name="gestos"),
    path("gestos/novo/", views.gesto_novo, name="gesto_novo"),
    path("gestos/<int:sinal_id>/", views.gesto_detalhe, name="gesto_detalhe"),
    path("gestos/<int:sinal_id>/gravar/", views.gesto_gravar, name="gesto_gravar"),
    path(
        "gestos/<int:sinal_id>/amostras/salvar/",
        views.gesto_amostra_salvar,
        name="gesto_amostra_salvar",
    ),
]
