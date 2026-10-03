"""Views do LibrAI."""
import json

from django.contrib import messages
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import SinalForm
from .models import AmostraMovimento, Sinal
from .movimentos import (
    AmostraInvalida,
    apagar_amostra,
    extrair_landmarks,
    salvar_amostra,
    validar_payload,
)
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
    """Cadastra um novo sinal (título, tipo e descrição)."""
    form = SinalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Sinal cadastrado com sucesso.")
        return redirect("gestos")
    return render(request, "libras/gesto_form.html", {"form": form})


def gesto_detalhe(request, sinal_id):
    """Página do sinal: dados cadastrais e amostras de movimento gravadas."""
    sinal = get_object_or_404(Sinal, pk=sinal_id)
    amostras = AmostraMovimento.objects.filter(sinal=sinal, ativo=True)
    return render(
        request,
        "libras/gesto_detalhe.html",
        {"sinal": sinal, "amostras": amostras},
    )


def gesto_gravar(request, sinal_id):
    """Página de gravação de amostra temporal para sinais de movimento."""
    sinal = get_object_or_404(Sinal, pk=sinal_id, tipo=Sinal.Tipo.MOVIMENTO)
    return render(request, "libras/gravar.html", {"sinal": sinal})


@require_POST
def gesto_amostra_salvar(request, sinal_id):
    """Extrai os landmarks dos frames recebidos e salva a amostra temporal.

    O id do sinal vem da própria rota (nunca do corpo da requisição) e só
    sinais de MOVIMENTO aceitam amostras. O processamento usa uma pipeline
    independente do reconhecimento estático.
    """
    sinal = get_object_or_404(Sinal, pk=sinal_id, tipo=Sinal.Tipo.MOVIMENTO)
    try:
        dados = json.loads(request.body.decode("utf-8"))
        frames = validar_payload(dados)
        sequencia = extrair_landmarks(frames)
        amostra = salvar_amostra(sinal, sequencia)
    except json.JSONDecodeError:
        return JsonResponse({"erro": "JSON inválido."}, status=400)
    except AmostraInvalida as exc:
        return JsonResponse({"erro": str(exc)}, status=400)
    return JsonResponse(
        {
            "ok": True,
            "amostra_id": amostra.pk,
            "quantidade_frames": amostra.quantidade_frames,
            "duracao_ms": amostra.duracao_ms,
        }
    )


@require_POST
def gesto_amostra_apagar(request, sinal_id, amostra_id):
    """Apaga uma amostra temporal do sinal (registro e arquivo JSON).

    A amostra precisa pertencer ao sinal da URL — IDs de outros sinais
    não são aceitos. GET nunca apaga, por segurança.
    """
    sinal = get_object_or_404(Sinal, pk=sinal_id)
    amostra = get_object_or_404(AmostraMovimento, pk=amostra_id, sinal=sinal)
    apagar_amostra(amostra)
    messages.success(request, f"Amostra #{amostra_id} apagada.")
    return redirect("gesto_detalhe", sinal_id=sinal.pk)
