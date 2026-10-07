"""Views do LibrAI."""
from django.contrib import messages
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import SinalForm
from .models import AmostraMovimento, Sinal
from .captura.camera import GravacaoIndisponivel, camera
from .movimento.amostras import AmostraInvalida, apagar_amostra


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
    """Estúdio de gravação: câmera ao vivo com os marcos da mão.

    Mesmo sistema do comando gravar_movimento — a câmera é a do
    reconhecimento (``libras.captura.camera``), então as amostras saem como o
    reconhecedor as verá.
    """
    sinal = get_object_or_404(
        Sinal, pk=sinal_id, tipo=Sinal.Tipo.MOVIMENTO, ativo=True
    )
    return render(request, "libras/gravar.html", {"sinal": sinal})


def _sinal_de_movimento(sinal_id):
    return get_object_or_404(
        Sinal, pk=sinal_id, tipo=Sinal.Tipo.MOVIMENTO, ativo=True
    )


@require_POST
def gesto_gravacao_iniciar(request, sinal_id):
    """Começa a gravar uma amostra do sinal (o id vem só da rota)."""
    sinal = _sinal_de_movimento(sinal_id)
    try:
        camera.iniciar_gravacao(sinal)
    except GravacaoIndisponivel as exc:
        return JsonResponse({"erro": str(exc)}, status=409)
    return JsonResponse({"ok": True})


@require_POST
def gesto_gravacao_parar(request, sinal_id):
    """Encerra a gravação e salva a amostra."""
    sinal = _sinal_de_movimento(sinal_id)
    try:
        amostra = camera.parar_gravacao(sinal)
    except GravacaoIndisponivel as exc:
        return JsonResponse({"erro": str(exc)}, status=409)
    except AmostraInvalida as exc:
        return JsonResponse({"erro": f"Amostra descartada: {exc}"}, status=400)
    return JsonResponse(
        {
            "ok": True,
            "amostra_id": amostra.pk,
            "quantidade_frames": amostra.quantidade_frames,
            "duracao_s": amostra.duracao_segundos,
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
