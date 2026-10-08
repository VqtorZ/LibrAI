"""Views do LibrAI.

A câmera é a do navegador de quem usa o site: lá o MediaPipe acha os 21
pontos da mão e só esses números chegam aqui (``/api/quadros/`` ao vivo,
e as rotas de gravação).
"""
import json
import re
from datetime import datetime
from string import ascii_uppercase

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.db.models import Avg, Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .acesso import FormularioTrocarSenha, apenas_admin
from .estatico import amostras as amostras_alfabeto
from .estatico.classificador import alfabeto as classificador_alfabeto
from .estatico.treino import ErroTreino
from .estatico.treino import treinar as treinar_modelo_alfabeto
from .forms import SinalForm
from .models import AmostraMovimento, Sinal
from .movimento import classificador, sessoes
from .movimento.amostras import (
    FORMATO_VERSAO,
    AmostraInvalida,
    apagar_amostra,
    apagar_sinal,
    salvar_amostra,
    sequencia_de_gravacao,
    validar_marcos,
    validar_quadros,
)

# Quadros por envio ao vivo (~8 por lote a cada 250 ms; folga para atrasos).
QUADROS_POR_LOTE = 90
CANAL_VALIDO = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def _json(request):
    """Corpo JSON da requisição (dicionário) ou AmostraInvalida."""
    try:
        dados = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AmostraInvalida("Dados inválidos.")
    if not isinstance(dados, dict):
        raise AmostraInvalida("Dados inválidos.")
    return dados


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
    estaticas = set(classificador_alfabeto.letras) if classificador_alfabeto.pronto else set()
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
            ativo=True, sinal__ativo=True, versao_features=FORMATO_VERSAO
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


@require_POST
def api_quadros(request):
    """Reconhecimento ao vivo: recebe um lote de quadros e devolve o estado.

    Público (o Reconhecer não exige conta). Cada aba manda um "canal"
    aleatório, que separa o detector de movimento de cada pessoa.
    """
    try:
        dados = _json(request)
        canal = dados.get("canal")
        if not isinstance(canal, str) or not CANAL_VALIDO.match(canal):
            raise AmostraInvalida("Canal inválido.")
        quadros = validar_quadros(dados.get("quadros"), maximo=QUADROS_POR_LOTE)
    except AmostraInvalida as exc:
        return JsonResponse({"erro": str(exc)}, status=400)
    estado = sessoes.sessao(canal).processar(quadros, classificador_alfabeto)
    return JsonResponse(estado)


@apenas_admin
def gestos(request):
    """Lista os sinais ativos, com amostras e situação no reconhecimento."""
    sinais = list(
        Sinal.objects.filter(ativo=True).annotate(
            total_amostras=Count(
                "amostras",
                filter=Q(amostras__ativo=True, amostras__versao_features=FORMATO_VERSAO),
            )
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
            "alfabeto_contagem": [
                {"letra": l, "amostras": contagem_alfabeto.get(l, 0)}
                for l in amostras_alfabeto.LETRAS_ESTATICAS
            ],
        },
    )


@apenas_admin
def gesto_novo(request):
    """Cadastra um novo sinal (título, tipo e descrição)."""
    form = SinalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Sinal cadastrado com sucesso.")
        return redirect("gestos")
    return render(request, "libras/gesto_form.html", {"form": form})


@apenas_admin
def gesto_detalhe(request, sinal_id):
    """Página do sinal: dados cadastrais e amostras de movimento gravadas."""
    sinal = get_object_or_404(Sinal, pk=sinal_id)
    todas = AmostraMovimento.objects.filter(sinal=sinal, ativo=True)
    amostras = todas.filter(versao_features=FORMATO_VERSAO)
    contexto = {
        "sinal": sinal,
        "amostras": amostras,
        "antigas": todas.exclude(versao_features=FORMATO_VERSAO),
        "total_todas": todas.count(),
    }
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


@apenas_admin
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


@apenas_admin
def gesto_gravar(request, sinal_id):
    """Estúdio de gravação: a câmera do navegador, com os pontos da mão.

    Mesmo caminho do reconhecimento ao vivo, então as amostras saem como o
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


@apenas_admin
@require_POST
def gesto_amostra_gravar(request, sinal_id):
    """Salva uma amostra gravada no navegador (o id do sinal vem só da rota)."""
    sinal = _sinal_de_movimento(sinal_id)
    try:
        sequencia = sequencia_de_gravacao(_json(request).get("quadros"))
        amostra = salvar_amostra(sinal, sequencia)
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


@apenas_admin
@require_POST
def gesto_amostras_apagar(request, sinal_id):
    """Apaga as amostras marcadas na tabela do sinal (uma, várias ou todas).

    Só valem ids de amostras deste sinal; os outros são ignorados.
    """
    sinal = get_object_or_404(Sinal, pk=sinal_id)
    ids = [int(i) for i in request.POST.getlist("amostra") if i.isdigit()]
    amostras = list(AmostraMovimento.objects.filter(sinal=sinal, pk__in=ids))
    for amostra in amostras:
        apagar_amostra(amostra)
    if amostras:
        total = len(amostras)
        messages.success(
            request,
            f"{total} amostra{'s' if total > 1 else ''} apagada{'s' if total > 1 else ''}. "
            "Treine de novo para o reconhecimento esquecer.",
        )
    else:
        messages.error(request, "Nenhuma amostra selecionada.")
    return redirect("gesto_detalhe", sinal_id=sinal.pk)


@apenas_admin
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


@apenas_admin
def alfabeto_gravar(request):
    """Estúdio do alfabeto: escolha a letra, faça o sinal, Espaço salva.

    A câmera e o detector de mão são os do navegador — o mesmo caminho do
    reconhecimento ao vivo.
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


@apenas_admin
@require_POST
def alfabeto_amostra_salvar(request):
    """Salva uma amostra da letra com os pontos da mão vistos no navegador."""
    try:
        dados = _json(request)
        letra = amostras_alfabeto.validar_letra(dados.get("letra"))
        marcos = validar_marcos(dados.get("marcos"))
        linha = amostras_alfabeto.salvar(letra, marcos)
    except (amostras_alfabeto.AmostraEstaticaInvalida, AmostraInvalida) as exc:
        return JsonResponse({"erro": str(exc)}, status=400)
    request.session["ultima_amostra_alfabeto"] = linha
    return JsonResponse(_resposta_contagem(letra))


@apenas_admin
@require_POST
def alfabeto_amostra_desfazer(request):
    """Remove a última amostra salva por este navegador (se ainda for a última)."""
    linha = request.session.pop("ultima_amostra_alfabeto", None)
    if not amostras_alfabeto.desfazer(linha):
        return JsonResponse({"erro": "Não há amostra para desfazer."}, status=409)
    return JsonResponse(_resposta_contagem(linha.split(",", 1)[0]))


# Ligações entre os 21 pontos da mão (as mesmas do desenho ao vivo).
CONEXOES_DA_MAO = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
    (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17),
    (17, 18), (18, 19), (19, 20),
)
PONTAS_DOS_DEDOS = {4, 8, 12, 16, 20}


def desenho_da_mao(valores, tamanho=100, margem=12):
    """Pontos e linhas (num quadro de ``tamanho``) para desenhar a mão em SVG.

    As coordenadas da amostra são relativas ao pulso; aqui elas só são
    centralizadas e ampliadas para caber no quadro, sem distorcer.
    """
    xs, ys = valores[0::3], valores[1::3]
    largura = (max(xs) - min(xs)) or 1.0
    altura = (max(ys) - min(ys)) or 1.0
    escala = (tamanho - 2 * margem) / max(largura, altura)
    dx = (tamanho - largura * escala) / 2 - min(xs) * escala
    dy = (tamanho - altura * escala) / 2 - min(ys) * escala
    pontos = [(round(x * escala + dx, 1), round(y * escala + dy, 1)) for x, y in zip(xs, ys)]
    return {
        "pontos": [{"x": x, "y": y, "ponta": i in PONTAS_DOS_DEDOS} for i, (x, y) in enumerate(pontos)],
        "linhas": [(*pontos[a], *pontos[b]) for a, b in CONEXOES_DA_MAO],
    }


@apenas_admin
def alfabeto_letra(request, letra):
    """Amostras de uma letra: ver cada mão gravada e apagar as ruins."""
    try:
        letra = amostras_alfabeto.validar_letra(letra)
    except amostras_alfabeto.AmostraEstaticaInvalida:
        raise Http404("Letra inválida.")
    amostras = amostras_alfabeto.listar(letra)
    for amostra in amostras:
        amostra["desenho"] = desenho_da_mao(amostra.pop("valores"))
    contagem = amostras_alfabeto.contar()
    letras = [{"letra": l, "amostras": contagem.get(l, 0)} for l in amostras_alfabeto.LETRAS_ESTATICAS]
    return render(
        request,
        "libras/alfabeto_letra.html",
        {"letra": letra, "amostras": amostras, "letras": letras},
    )


@apenas_admin
@require_POST
def alfabeto_amostras_apagar(request, letra):
    """Apaga as amostras marcadas da letra (uma, várias ou todas)."""
    try:
        letra = amostras_alfabeto.validar_letra(letra)
    except amostras_alfabeto.AmostraEstaticaInvalida:
        raise Http404("Letra inválida.")
    total = amostras_alfabeto.apagar(letra, request.POST.getlist("amostra"))
    if total:
        messages.success(
            request,
            f"{total} amostra{'s' if total > 1 else ''} da letra {letra} "
            f"apagada{'s' if total > 1 else ''}. Treine o alfabeto de novo para o reconhecimento esquecer.",
        )
    else:
        messages.error(request, "Nenhuma amostra apagada (nada selecionado ou já tinha sido apagada).")
    return redirect("alfabeto_letra", letra=letra)


@apenas_admin
@require_POST
def treinar_alfabeto(request):
    """Treina o alfabeto pelo site (mesmo treino do comando treinar_alfabeto).

    Leva poucos segundos; o reconhecimento recarrega o modelo sozinho.
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
@apenas_admin
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


# --------------------------------------------------------------------------
# Conta: trocar a própria senha
# --------------------------------------------------------------------------
class TrocarSenha(auth_views.PasswordChangeView):
    """Cada administrador troca a própria senha (continua logado depois)."""

    template_name = "libras/trocar_senha.html"
    form_class = FormularioTrocarSenha

    def get_success_url(self):
        return reverse("gestos")

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, "Senha trocada. Use a nova senha no próximo login.")
        return resposta


trocar_senha = apenas_admin(TrocarSenha.as_view())

