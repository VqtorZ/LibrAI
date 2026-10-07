"""Views do LibrAI."""
from datetime import datetime
from string import ascii_uppercase

from django.contrib import messages
from django.db.models import Avg, Count, Q
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .captura.camera import GravacaoIndisponivel, camera
from .estatico import amostras as amostras_alfabeto
from .estatico.treino import ErroTreino
from .estatico.treino import treinar as treinar_modelo_alfabeto
from .forms import SinalForm
from .models import AmostraMovimento, Sinal
from .movimento import classificador
from .movimento.amostras import AmostraInvalida, apagar_amostra, apagar_sinal


def _modelo_de_movimentos():
    """Modelo de movimentos treinado, ou None se ainda não houver."""
    try:
        return classificador.carregar_modelo()
    except classificador.ErroTemporal:
        return None


def _alfabeto():
    """A–Z com o que o LibrAI já reconhece, a partir dos modelos reais.

    Devolve ``(alfabeto, movimento)``: a lista de ``{"letra", "tipo"}``
    (``estatico``, ``movimento`` ou ``pendente``) e as classes do modelo
    de movimentos.
    """
    estaticas = {str(c) for c in getattr(camera.model, "classes_", [])}
    modelo = _modelo_de_movimentos()
    movimento = set(modelo["classes"]) if modelo else set()
    alfabeto = [
        {
            "letra": letra,
            "tipo": "movimento" if letra in movimento
            else "estatico" if letra in estaticas else "pendente",
        }
        for letra in ascii_uppercase
    ]
    return alfabeto, movimento


def _voltar(request):
    """Página para onde voltar depois de um POST (só endereços deste site)."""
    voltar = request.POST.get("voltar") or reverse("gestos")
    if not url_has_allowed_host_and_scheme(voltar, allowed_hosts={request.get_host()}):
        return reverse("gestos")
    return voltar


def _total_reconhecidas(alfabeto):
    return sum(1 for item in alfabeto if item["tipo"] != "pendente")


def inicio(request):
    """Home: apresenta o projeto com o que o LibrAI reconhece de verdade hoje."""
    alfabeto, movimento = _alfabeto()
    contexto = {
        "alfabeto": alfabeto,
        "total_letras": _total_reconhecidas(alfabeto),
        # Letras que a demonstração da home mostra como "reconhecidas".
        "letras_demo": [item["letra"] for item in alfabeto if item["tipo"] != "pendente"],
        "total_movimento": len(movimento),
        "total_amostras": AmostraMovimento.objects.filter(
            ativo=True, sinal__ativo=True
        ).count(),
        "total_sinais": Sinal.objects.filter(ativo=True).count(),
    }
    return render(request, "libras/inicio.html", contexto)


def reconhecer(request):
    """Reconhecimento ao vivo, com a grade do que o LibrAI já reconhece."""
    alfabeto, _ = _alfabeto()
    return render(
        request,
        "libras/reconhecer.html",
        {"alfabeto": alfabeto, "total_letras": _total_reconhecidas(alfabeto)},
    )


def video(request):
    return StreamingHttpResponse(
        camera.frames(), content_type="multipart/x-mixed-replace; boundary=frame"
    )


def status(request):
    return JsonResponse(camera.status())


def gestos(request):
    """Lista os sinais ativos, com amostras e situação no reconhecimento."""
    sinais = list(
        Sinal.objects.filter(ativo=True).annotate(
            total_amostras=Count("amostras", filter=Q(amostras__ativo=True))
        )
    )
    de_movimento = [s for s in sinais if s.tipo == Sinal.Tipo.MOVIMENTO]
    situacoes = classificador.situacao_dos_sinais(de_movimento)
    for sinal in sinais:
        sinal.situacao = situacoes.get(sinal.pk)
    precisa_treinar = any(
        s["codigo"] == "treinar" for s in situacoes.values()
    )
    contagem_alfabeto = amostras_alfabeto.contar()
    return render(
        request,
        "libras/gestos.html",
        {
            "sinais": sinais,
            "precisa_treinar": precisa_treinar,
            "tem_movimento": bool(de_movimento),
            "alfabeto_letras": len(contagem_alfabeto),
            "alfabeto_amostras": sum(contagem_alfabeto.values()),
        },
    )


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
    contexto = {"sinal": sinal, "amostras": amostras}
    if sinal.tipo == Sinal.Tipo.MOVIMENTO:
        medias = amostras.aggregate(duracao=Avg("duracao_ms"), fps=Avg("fps"))
        modelo = _modelo_de_movimentos()
        contexto.update({
            "duracao_media_s": (medias["duracao"] or 0) / 1000,
            "fps_medio": medias["fps"] or 0,
            "situacao": classificador.situacao_dos_sinais([sinal])[sinal.pk],
            "modelo_treinado_em": (
                datetime.fromisoformat(modelo["treinado_em"]) if modelo else None
            ),
        })
    return render(request, "libras/gesto_detalhe.html", contexto)


@require_POST
def treinar_movimentos(request):
    """Treina o modelo de movimentos pelo site (mesmo treino do comando).

    O reconhecimento ao vivo recarrega o modelo sozinho quando o
    arquivo muda. Com dezenas de amostras o treino leva poucos
    segundos; volta para a página de onde o pedido veio.
    """
    voltar = _voltar(request)
    try:
        treino = classificador.treinar()
    except classificador.ErroTemporal as exc:
        messages.error(request, f"Não foi possível treinar: {exc}")
        return redirect(voltar)
    modelo = treino.modelo
    sinais = ", ".join(
        f"{c} ({modelo['amostras_por_classe'][c]} amostras)" for c in modelo["classes"]
    )
    texto = f"Modelo treinado: {sinais}"
    if modelo["negativos"]:
        texto += f" e {len(modelo['negativos'])} exemplo(s) negativo(s)"
    messages.success(request, texto + ". O reconhecimento ao vivo já usa o modelo novo.")
    for classe, quantidade in treino.excluidas:
        messages.warning(
            request, f"{classe} ficou de fora: tem {quantidade} amostra (mínimo 2)."
        )
    if treino.invalidas:
        messages.warning(
            request,
            f"{len(treino.invalidas)} amostra(s) com problema foram ignoradas "
            "(rode verificar_movimentos para detalhes).",
        )
    for classe in modelo["classes"]:
        if modelo["calibracao"][classe]["sobreposicao"]:
            messages.warning(
                request,
                f"Um exemplo negativo está tão perto de {classe} quanto os próprios "
                f"exemplos de {classe}. Revise as gravações negativas.",
            )
    return redirect(voltar)


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


# --------------------------------------------------------------------------
# Alfabeto estático: gravar amostras pelo site e treinar
# --------------------------------------------------------------------------
def _resposta_contagem(letra):
    contagem = amostras_alfabeto.contar()
    return {
        "ok": True,
        "letra": letra,
        "total_letra": contagem.get(letra, 0),
        "total": sum(contagem.values()),
    }


def alfabeto_gravar(request):
    """Estúdio do alfabeto: escolha a letra, faça o sinal, Espaço salva.

    Mesmo sistema do comando coletar_alfabeto, mas no site e com a
    câmera (e o detector de mão) do reconhecimento ao vivo.
    """
    contagem = amostras_alfabeto.contar()
    tipos = {item["letra"]: item["tipo"] for item in _alfabeto()[0]}
    letra = (request.GET.get("letra") or "A").upper()
    if letra not in amostras_alfabeto.LETRAS_ESTATICAS:
        letra = "A"
    letras = [
        {
            "letra": l,
            "amostras": contagem.get(l, 0),
            "reconhece": tipos.get(l) == "estatico",
        }
        for l in amostras_alfabeto.LETRAS_ESTATICAS
    ]
    return render(
        request,
        "libras/alfabeto_gravar.html",
        {
            "letras": letras,
            "letra_inicial": letra,
            "total_amostras": sum(contagem.values()),
        },
    )


@require_POST
def alfabeto_amostra_salvar(request):
    """Salva uma amostra da letra com a mão que a câmera está vendo agora."""
    try:
        letra = amostras_alfabeto.validar_letra(request.POST.get("letra"))
        linha = amostras_alfabeto.salvar(letra, camera.marcos_recentes())
    except amostras_alfabeto.AmostraEstaticaInvalida as exc:
        return JsonResponse({"erro": str(exc)}, status=400)
    except GravacaoIndisponivel as exc:
        return JsonResponse({"erro": str(exc)}, status=409)
    request.session["ultima_amostra_alfabeto"] = linha
    return JsonResponse(_resposta_contagem(letra))


@require_POST
def alfabeto_amostra_desfazer(request):
    """Remove a última amostra salva por este navegador (se ainda for a última)."""
    linha = request.session.pop("ultima_amostra_alfabeto", None)
    if not amostras_alfabeto.desfazer(linha):
        return JsonResponse({"erro": "Não há amostra para desfazer."}, status=409)
    return JsonResponse(_resposta_contagem(linha.split(",", 1)[0]))


@require_POST
def treinar_alfabeto(request):
    """Treina o alfabeto pelo site (mesmo treino do comando treinar_alfabeto).

    Leva poucos segundos; a câmera recarrega o modelo sozinha.
    """
    voltar = _voltar(request)
    try:
        treinar_modelo_alfabeto()
    except ErroTreino as exc:
        messages.error(request, f"Não foi possível treinar o alfabeto: {exc}")
        return redirect(voltar)
    contagem = amostras_alfabeto.contar()
    messages.success(
        request,
        f"Alfabeto treinado com {len(contagem)} letras e {sum(contagem.values())} "
        "amostras. O reconhecimento ao vivo já usa o modelo novo.",
    )
    return redirect(voltar)


# --------------------------------------------------------------------------
# Excluir um sinal inteiro
# --------------------------------------------------------------------------
def gesto_excluir(request, sinal_id):
    """Exclui o sinal: cadastro, amostras e o que o modelo aprendeu dele.

    GET mostra a confirmação (usada quando o navegador não abre a janela
    de confirmação da página do sinal); só o POST exclui.
    """
    sinal = get_object_or_404(Sinal, pk=sinal_id)
    if request.method != "POST":
        return render(
            request,
            "libras/gesto_excluir.html",
            {"sinal": sinal, "total_amostras": sinal.amostras.count()},
        )
    titulo = sinal.titulo
    if sinal.tipo == Sinal.Tipo.MOVIMENTO:
        try:
            no_modelo = classificador.remover_do_modelo(sinal.pk, titulo)
        except OSError as exc:
            messages.error(request, f"Não foi possível atualizar o modelo, nada foi excluído: {exc}")
            return redirect("gesto_detalhe", sinal_id=sinal.pk)
    else:
        no_modelo = None
    total = apagar_sinal(sinal)
    texto = f"Sinal {titulo} excluído"
    if total:
        texto += f", com {total} amostra{'s' if total != 1 else ''}"
    texto += "."
    if no_modelo == "removido":
        texto += " O reconhecimento deixou de usá-lo; os outros sinais continuam como estavam."
    elif no_modelo == "modelo_apagado":
        texto += " Era o último sinal do modelo de movimentos, que foi apagado."
    messages.success(request, texto)
    return redirect("gestos")

