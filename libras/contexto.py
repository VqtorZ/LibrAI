"""Variáveis disponíveis em todos os templates."""
from django.conf import settings

# Arquivos estáticos que mudam com frequência (CSS e o JS da câmera).
ESTILOS = ("css/app.css", "css/home.css", "css/reconhecer.css", "css/entrar.css", "js/camera-maos.js", "js/detector-maos-worker.js")


def versao_estaticos(request):
    """Versão dos arquivos de estilo, para o navegador não usar cópia velha.

    Os templates usam ``{% static 'css/app.css' %}?v={{ versao_estaticos }}``:
    quando um CSS muda, o endereço muda junto e o navegador baixa o novo
    (o servidor de desenvolvimento não manda cabeçalhos de cache).
    """
    versao = 0
    for pasta in settings.STATICFILES_DIRS:
        for nome in ESTILOS:
            try:
                versao = max(versao, int((pasta / nome).stat().st_mtime))
            except OSError:
                continue
    return {"versao_estaticos": versao}
