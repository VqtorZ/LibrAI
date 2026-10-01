from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("reconhecer/", views.recognizer, name="recognizer"),
    path("video/", views.video_feed, name="video_feed"),
    path("api/status/", views.status, name="status"),
]
