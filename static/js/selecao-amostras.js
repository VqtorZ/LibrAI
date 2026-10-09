// Seleção de amostras para excluir (letras do alfabeto e sinais de movimento).
//
// A página marca o bloco com data-selecao="<id do formulário em lote>" e
// data-rotulo="da letra A" (vai na pergunta). As caixinhas usam
// form="<id do formulário>" e name="amostra" (e data-grupo="treinada"/"nova"
// para os atalhos "Só as treinadas"/"Só as novas"). Formulários de uma
// amostra só têm data-excluir-uma="#12"; o de tirar a letra do
// reconhecimento, data-tirar="A". Tudo passa pela janela de confirmação
// (_confirmar_amostras.html) antes de enviar.
(function () {
    const janela = document.getElementById('janela-amostras');
    const titulo = document.getElementById('titulo-amostras');
    const texto = document.getElementById('texto-amostras');
    const aviso = janela && janela.querySelector('.excluir-aviso');
    const sim = document.getElementById('confirmar-amostras');
    let formAlvo = null;

    function confirmar(form, mensagem, opcoes = {}) {
        const { cabecalho = 'Excluir amostras?', botao = 'Sim, excluir', definitivo = true } = opcoes;
        if (!janela || !janela.showModal) {
            if (window.confirm(definitivo ? `${mensagem} Esta ação não pode ser desfeita.` : mensagem)) form.submit();
            return;
        }
        formAlvo = form;
        titulo.textContent = cabecalho;
        texto.textContent = mensagem;
        sim.textContent = botao;
        aviso.hidden = !definitivo;
        janela.showModal();
    }

    if (janela) {
        // form.submit() não dispara o evento "submit": não pergunta de novo.
        sim.addEventListener('click', () => {
            if (formAlvo) formAlvo.submit();
        });
        janela.addEventListener('click', (evento) => {
            if (evento.target === janela || evento.target.closest('[data-fechar]')) janela.close();
        });
    }

    // Tirar a letra do reconhecimento (existe mesmo sem amostras na página).
    const formTirar = document.querySelector('form[data-tirar]');
    if (formTirar) {
        formTirar.addEventListener('submit', (evento) => {
            evento.preventDefault();
            const letra = formTirar.dataset.tirar;
            confirmar(
                formTirar,
                `O reconhecimento deixa de ler a letra ${letra}. As amostras dela ficam guardadas, e ela volta no próximo "Treinar alfabeto".`,
                { cabecalho: `Tirar a letra ${letra} do reconhecimento?`, botao: 'Sim, tirar', definitivo: false },
            );
        });
    }

    const raiz = document.querySelector('[data-selecao]');
    if (!raiz) return;
    const formLote = document.getElementById(raiz.dataset.selecao);
    const rotulo = raiz.dataset.rotulo || '';
    const caixas = [...document.querySelectorAll(`input[type="checkbox"][form="${formLote.id}"]`)];
    const todas = document.getElementById('selecionar-todas');
    const contador = document.getElementById('total-selecionadas');
    const botaoLote = document.getElementById('excluir-selecionadas');

    const marcadas = () => caixas.filter((caixa) => caixa.checked).length;

    function atualizar() {
        const n = marcadas();
        contador.textContent = n === 0 ? 'nenhuma selecionada' : n === 1 ? '1 selecionada' : `${n} selecionadas`;
        botaoLote.disabled = n === 0;
        if (todas) {
            todas.checked = n > 0 && n === caixas.length;
            todas.indeterminate = n > 0 && n < caixas.length;
        }
    }

    if (todas) {
        todas.addEventListener('change', () => {
            caixas.forEach((caixa) => { caixa.checked = todas.checked; });
            atualizar();
        });
    }
    // "Só as treinadas" / "Só as novas": marca exatamente aquele grupo.
    document.querySelectorAll('[data-marcar]').forEach((botao) => {
        botao.addEventListener('click', () => {
            caixas.forEach((caixa) => { caixa.checked = caixa.dataset.grupo === botao.dataset.marcar; });
            atualizar();
        });
    });
    caixas.forEach((caixa) => caixa.addEventListener('change', atualizar));

    formLote.addEventListener('submit', (evento) => {
        evento.preventDefault();
        const n = marcadas();
        if (!n) return;
        const mensagem = n === caixas.length && n > 1
            ? `Excluir TODAS as ${n} amostras ${rotulo}?`
            : `Excluir ${n === 1 ? '1 amostra' : `${n} amostras`} ${rotulo}?`;
        confirmar(formLote, mensagem);
    });

    document.querySelectorAll('form[data-excluir-uma]').forEach((form) => {
        form.addEventListener('submit', (evento) => {
            evento.preventDefault();
            confirmar(form, `Excluir a amostra ${form.dataset.excluirUma} ${rotulo}?`);
        });
    });

    atualizar();
})();
