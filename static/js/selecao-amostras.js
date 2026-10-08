// Seleção de amostras para excluir (letras do alfabeto e sinais de movimento).
//
// A página marca o bloco com data-selecao="<id do formulário em lote>" e
// data-rotulo="da letra A" (vai na pergunta). As caixinhas usam
// form="<id do formulário>" e name="amostra". Formulários de uma amostra só
// têm data-excluir-uma="#12". Tudo passa pela janela de confirmação
// (_confirmar_amostras.html) antes de apagar.
(function () {
    const raiz = document.querySelector('[data-selecao]');
    if (!raiz) return;
    const formLote = document.getElementById(raiz.dataset.selecao);
    const rotulo = raiz.dataset.rotulo || '';
    const caixas = [...document.querySelectorAll(`input[type="checkbox"][form="${formLote.id}"]`)];
    const todas = document.getElementById('selecionar-todas');
    const contador = document.getElementById('total-selecionadas');
    const botaoLote = document.getElementById('excluir-selecionadas');
    const janela = document.getElementById('janela-amostras');
    const texto = document.getElementById('texto-amostras');
    const sim = document.getElementById('confirmar-amostras');
    let formAlvo = null;

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

    function confirmar(form, mensagem) {
        if (!janela || !janela.showModal) {
            if (window.confirm(`${mensagem} Esta ação não pode ser desfeita.`)) form.submit();
            return;
        }
        formAlvo = form;
        texto.textContent = mensagem;
        janela.showModal();
    }

    if (todas) {
        todas.addEventListener('change', () => {
            caixas.forEach((caixa) => { caixa.checked = todas.checked; });
            atualizar();
        });
    }
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

    if (janela) {
        // form.submit() não dispara o evento "submit": não pergunta de novo.
        sim.addEventListener('click', () => {
            if (formAlvo) formAlvo.submit();
        });
        janela.addEventListener('click', (evento) => {
            if (evento.target === janela || evento.target.closest('[data-fechar]')) janela.close();
        });
    }
    atualizar();
})();
