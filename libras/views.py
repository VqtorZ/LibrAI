from django.contrib import messages
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render

from .forms import SinalForm
from .models import Sinal
from .vision import camera


def home(request):
    return render(request, "libras/home.html")


def recognizer(request):
    return render(request, "libras/recognizer.html")


def video_feed(request):
    return StreamingHttpResponse(
        camera.frames(), content_type="multipart/x-mixed-replace; boundary=frame"
    )


def status(request):
    return JsonResponse(camera.status())


def gestos(request):
    """Lista os sinais ativos cadastrados para o LibrAI."""
    sinais = Sinal.objects.filter(ativo=True)
    return render(request, "libras/gestos.html", {"sinais": sinais})


def gesto_novo(request):
    """Cadastra um novo sinal (título e descrição)."""
    form = SinalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Sinal cadastrado com sucesso.")
        return redirect("gestos")
    return render(request, "libras/gesto_form.html", {"form": form})
