// Câmera do navegador + detector de mão (MediaPipe Tasks Vision).
//
// Usado pelo Reconhecer, Gravar letras e Gravar movimento. A câmera é a
// de quem está usando o site; só os 21 pontos da mão vão para o servidor.
// A análise roda num Web Worker (detector-maos-worker.js) para não travar
// o vídeo; se o navegador não permitir, roda na própria página.
//
// Formato dos pontos (versão 3, o mesmo das amostras e dos modelos):
//  - espelhados como numa selfie: x' = 1 - x, e a mão "Left"/"Right"
//    trocada (o MediaPipe vê a imagem sem espelhar);
//  - x e z multiplicados pela proporção da imagem (largura / altura), para
//    que webcams 16:9 e 4:3 deem os mesmos números para o mesmo gesto.

const VERSAO_MEDIAPIPE = '0.10.21';
const CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSAO_MEDIAPIPE}`;

// Conexões entre os 21 pontos (as mesmas do MediaPipe Hands).
const CONEXOES = [
    [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10],
    [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17],
    [17, 18], [18, 19], [19, 20],
];
const PONTAS = new Set([4, 8, 12, 16, 20]);

// Reserva (detector na própria página): em computadores lentos, ele
// descansa entre análises, mas nunca abaixo de 15 por segundo — o
// reconhecimento de movimento já trabalha a 15 por segundo.
const INTERVALO_MAXIMO_MS = 66;

function arredondar(valor) {
    return Math.round(valor * 100000) / 100000;
}

function quadroDe(resultado, instante, proporcao) {
    const t = Math.round(instante);
    const pontos = resultado.landmarks && resultado.landmarks[0];
    if (!pontos) return { t, marcos: null, mao: null };
    const marcos = [];
    for (const p of pontos) {
        marcos.push(arredondar((1 - p.x) * proporcao), arredondar(p.y), arredondar(p.z * proporcao));
    }
    const lado = resultado.handedness && resultado.handedness[0] && resultado.handedness[0][0];
    const nome = lado ? lado.categoryName : null;
    const mao = nome === 'Left' ? 'Right' : nome === 'Right' ? 'Left' : null;
    return { t, marcos, mao };
}

function desenhar(contexto, resultado, largura, altura) {
    contexto.clearRect(0, 0, largura, altura);
    const pontos = resultado.landmarks && resultado.landmarks[0];
    if (!pontos) return;
    // O vídeo aparece espelhado (CSS); os pontos são desenhados espelhados também.
    const xy = pontos.map((p) => [(1 - p.x) * largura, p.y * altura]);
    const escala = Math.max(largura / 960, 0.6);
    contexto.lineWidth = 4 * escala;
    contexto.lineCap = 'round';
    contexto.strokeStyle = 'rgba(141, 179, 236, 0.95)';
    contexto.beginPath();
    for (const [a, b] of CONEXOES) {
        contexto.moveTo(xy[a][0], xy[a][1]);
        contexto.lineTo(xy[b][0], xy[b][1]);
    }
    contexto.stroke();
    xy.forEach(([x, y], i) => {
        contexto.beginPath();
        contexto.arc(x, y, (PONTAS.has(i) ? 7 : 5) * escala, 0, Math.PI * 2);
        contexto.fillStyle = PONTAS.has(i) ? '#FCA973' : '#FFFFFF';
        contexto.fill();
        contexto.lineWidth = 2.5 * escala;
        contexto.strokeStyle = PONTAS.has(i) ? '#FDE7D4' : '#78A4E6';
        contexto.stroke();
    });
}

// Imagem analisada: no máximo 640 px de largura (a mesma proporção da
// câmera, então os pontos normalizados não mudam). Menos pixels para
// enviar e processar; o modelo trabalha em 224 px de qualquer jeito.
const LARGURA_ANALISE = 640;

/** Medidas de desempenho (janela dos últimos 2 s), para o modo diagnóstico. */
export const medidas = {
    processador: null,
    resolucao: null,
    fpsCamera: 0,
    fpsDeteccao: 0,
    msDeteccao: 0,
    msDesenho: 0,
    _quadrosCamera: [],
    _deteccoes: [],
    registrarQuadroCamera(agora) {
        this._quadrosCamera.push(agora);
    },
    registrarDeteccao(agora, msDeteccao, msDesenho) {
        this._deteccoes.push([agora, msDeteccao, msDesenho]);
    },
    atualizar(agora) {
        const limite = agora - 2000;
        this._quadrosCamera = this._quadrosCamera.filter((t) => t >= limite);
        this._deteccoes = this._deteccoes.filter(([t]) => t >= limite);
        this.fpsCamera = this._quadrosCamera.length / 2;
        this.fpsDeteccao = this._deteccoes.length / 2;
        const n = this._deteccoes.length || 1;
        this.msDeteccao = this._deteccoes.reduce((soma, d) => soma + d[1], 0) / n;
        this.msDesenho = this._deteccoes.reduce((soma, d) => soma + d[2], 0) / n;
    },
};

/*
 * "Motores" de detecção. Os dois têm a mesma cara:
 *   livre()                          → pode analisar uma imagem agora?
 *   analisar(video, instante, entregar) → entregar(resultado, instante, ms)
 *   fechar()
 */

/** Principal: o detector roda num Web Worker, sem travar o vídeo e a página. */
async function criarMotorWorker(modeloUrl) {
    const endereco = new URL('./detector-maos-worker.js', import.meta.url);
    endereco.search = new URL(import.meta.url).search; // mesma versão (?v=) deste arquivo
    const worker = new Worker(endereco);
    let ocupado = false;
    let entregarAtual = null;
    try {
        await new Promise((pronto, falhou) => {
            const tempo = setTimeout(() => falhou(new Error('O detector demorou demais para carregar.')), 45000);
            worker.onmessage = ({ data }) => {
                if (data.tipo === 'pronto') {
                    clearTimeout(tempo);
                    console.info(`Detector de mão iniciado (${data.processador}, worker).`);
                    medidas.processador = `${data.processador} (worker)`;
                    pronto();
                } else if (data.tipo === 'erro') {
                    clearTimeout(tempo);
                    falhou(new Error(data.mensagem));
                }
            };
            worker.onerror = (evento) => {
                evento.preventDefault();
                clearTimeout(tempo);
                falhou(new Error(evento.message || 'Falha no worker do detector.'));
            };
            worker.postMessage({ tipo: 'iniciar', modeloUrl: new URL(modeloUrl, location.href).href });
        });
    } catch (falha) {
        worker.terminate();
        throw falha;
    }
    worker.onmessage = ({ data }) => {
        if (data.tipo === 'processador') {
            medidas.processador = `${data.processador} (worker)`;
            console.info(`Detector de mão: ${data.processador} foi mais rápido nesta máquina.`);
            return;
        }
        if (data.tipo !== 'resultado') return;
        ocupado = false;
        if (data.ignorado || data.erro || !entregarAtual) return;
        const resultado = {
            landmarks: data.pontos ? [data.pontos.map(([x, y, z]) => ({ x, y, z }))] : [],
            handedness: data.lado ? [[{ categoryName: data.lado }]] : [],
        };
        entregarAtual(resultado, data.instante, data.ms);
    };
    return {
        livre: () => !ocupado,
        analisar(video, instante, entregar) {
            ocupado = true;
            entregarAtual = entregar;
            const largura = Math.min(LARGURA_ANALISE, video.videoWidth);
            const altura = Math.round(video.videoHeight * largura / video.videoWidth);
            createImageBitmap(video, { resizeWidth: largura, resizeHeight: altura, resizeQuality: 'low' })
                .then((imagem) => worker.postMessage({ tipo: 'quadro', imagem, instante }, [imagem]))
                .catch(() => { ocupado = false; });
        },
        fechar: () => worker.terminate(),
    };
}

/** Reserva (navegadores sem worker com OffscreenCanvas): roda na própria página. */
async function criarMotorPagina(modeloUrl) {
    const { FilesetResolver, HandLandmarker } = await import(`${CDN}/vision_bundle.mjs`);
    const arquivos = await FilesetResolver.forVisionTasks(`${CDN}/wasm`);
    const opcoes = (delegate) => ({
        baseOptions: { modelAssetPath: modeloUrl, delegate },
        runningMode: 'VIDEO',
        numHands: 1,
        minHandDetectionConfidence: 0.6,
        minHandPresenceConfidence: 0.6,
        minTrackingConfidence: 0.5,
    });
    let detector;
    try {
        detector = await HandLandmarker.createFromOptions(arquivos, opcoes('GPU'));
        medidas.processador = 'GPU (página)';
    } catch (falha) {
        detector = await HandLandmarker.createFromOptions(arquivos, opcoes('CPU'));
        medidas.processador = 'CPU (página)';
    }
    let ultimaDeteccao = -Infinity;
    let msMedio = 0; // média móvel do tempo de cada detecção
    return {
        // Em computador lento, descansa entre análises (~metade do tempo da
        // página), sem cair abaixo de 15 por segundo.
        livre: () => performance.now() - ultimaDeteccao >= Math.min(msMedio, INTERVALO_MAXIMO_MS),
        analisar(video, instante, entregar) {
            const resultado = detector.detectForVideo(video, instante);
            const ms = performance.now() - instante;
            ultimaDeteccao = instante;
            msMedio = msMedio ? msMedio * 0.9 + ms * 0.1 : ms;
            entregar(resultado, instante, ms);
        },
        fechar: () => detector.close(),
    };
}

async function criarMotor(modeloUrl) {
    if (window.Worker && window.createImageBitmap && window.OffscreenCanvas) {
        try {
            return await criarMotorWorker(modeloUrl);
        } catch (falha) {
            console.warn('Detector em worker indisponível; usando a própria página.', falha);
        }
    }
    return criarMotorPagina(modeloUrl);
}

const MENSAGENS = {
    NotAllowedError: 'O acesso à câmera foi negado. Libere a câmera nas configurações do navegador (ícone ao lado do endereço) e tente de novo.',
    NotFoundError: 'Nenhuma câmera foi encontrada neste aparelho.',
    NotReadableError: 'A câmera está sendo usada por outro programa. Feche-o e tente de novo.',
    SecurityError: 'O navegador só libera a câmera em sites seguros (https).',
};

/**
 * Liga a câmera e o detector de mão.
 * @param {{video: HTMLVideoElement, canvas: HTMLCanvasElement, modeloUrl: string,
 *          aoQuadro: function, aoEstado: function}} opcoes
 *   aoQuadro({t, marcos, mao}) a cada imagem analisada;
 *   aoEstado(estado, mensagem) com 'carregando' | 'pedindo-camera' | 'ao-vivo' | 'erro'.
 */
export async function ligarCameraMaos({ video, canvas, modeloUrl, aoQuadro, aoEstado }) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        aoEstado('erro', MENSAGENS.SecurityError);
        return null;
    }
    let motor;
    let fluxo;
    try {
        aoEstado('carregando');
        motor = await criarMotor(modeloUrl);
        aoEstado('pedindo-camera');
        fluxo = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 960 }, height: { ideal: 540 }, facingMode: 'user' },
            audio: false,
        });
    } catch (falha) {
        if (motor) motor.fechar();
        const mensagem = MENSAGENS[falha && falha.name]
            || 'Não foi possível iniciar o detector de mão. Verifique a internet e recarregue a página.';
        aoEstado('erro', mensagem);
        return null;
    }
    video.srcObject = fluxo;
    video.muted = true;
    video.playsInline = true;
    await video.play().catch(() => {});
    const contexto = canvas.getContext('2d');
    let rodando = true;
    aoEstado('ao-vivo');

    function entregar(resultado, instante, msDeteccao) {
        if (!rodando) return;
        if (canvas.width !== video.videoWidth) {
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
        }
        const antes = performance.now();
        desenhar(contexto, resultado, canvas.width, canvas.height);
        medidas.registrarDeteccao(instante, msDeteccao, performance.now() - antes);
        aoQuadro(quadroDe(resultado, instante, video.videoWidth / video.videoHeight));
    }

    function novoQuadro(agora) {
        medidas.registrarQuadroCamera(agora);
        if (!video.videoWidth || !motor.livre()) return; // ocupado: pula esta imagem
        medidas.resolucao = `${video.videoWidth}×${video.videoHeight}`;
        motor.analisar(video, performance.now(), entregar);
    }

    // Uma análise por quadro NOVO da câmera (o laço por requestAnimationFrame
    // analisava a mesma imagem 3 a 4 vezes).
    if (video.requestVideoFrameCallback) {
        const aCadaQuadro = (agora) => {
            if (!rodando) return;
            novoQuadro(agora);
            video.requestVideoFrameCallback(aCadaQuadro);
        };
        video.requestVideoFrameCallback(aCadaQuadro);
    } else {
        // Navegadores sem requestVideoFrameCallback: confere se a imagem mudou.
        let ultimoTempo = -1;
        const passo = () => {
            if (!rodando) return;
            if (video.readyState >= 2 && video.currentTime !== ultimoTempo) {
                ultimoTempo = video.currentTime;
                novoQuadro(performance.now());
            }
            requestAnimationFrame(passo);
        };
        requestAnimationFrame(passo);
    }

    return {
        parar() {
            rodando = false;
            fluxo.getTracks().forEach((trilha) => trilha.stop());
            motor.fechar();
        },
    };
}

function canalAleatorio() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Array.from({ length: 24 }, () => Math.floor(Math.random() * 36).toString(36)).join('');
}

/**
 * Manda os quadros ao servidor em lotes (reconhecimento ao vivo) e entrega
 * cada resposta a aoResposta. Um "canal" aleatório separa esta aba das outras.
 */
export function criarEnvioAoVivo({ url, csrf, aoResposta, intervalo = 250 }) {
    const canal = canalAleatorio();
    let fila = [];
    let enviando = false;
    setInterval(async () => {
        if (enviando || !fila.length) return;
        const lote = fila;
        fila = [];
        enviando = true;
        try {
            const resposta = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                body: JSON.stringify({ canal, quadros: lote }),
            });
            if (resposta.ok) aoResposta(await resposta.json());
        } catch (falha) { /* rede instável: o próximo lote tenta de novo */ }
        enviando = false;
    }, intervalo);
    return {
        adicionar(quadro) {
            fila.push(quadro);
            if (fila.length > 80) fila = fila.slice(-80);
        },
    };
}

/** POST com JSON e CSRF; devolve o JSON da resposta ou lança Error com a mensagem do servidor. */
export async function enviarJson(url, csrf, corpo) {
    const resposta = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify(corpo),
    });
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok || !dados.ok) throw new Error(dados.erro || 'Falha de comunicação com o servidor.');
    return dados;
}

const TEXTOS_DO_AVISO = {
    carregando: 'Carregando o detector de mão…',
    'pedindo-camera': 'Permita o acesso à câmera para começar.',
};

/**
 * Liga a câmera da página (bloco _camera_navegador.html): mostra o aviso de
 * cada etapa, o indicador "Mão detectada" e o botão "Tentar de novo".
 * aoQuadro recebe cada quadro {t, marcos, mao}.
 */
export function iniciarCameraDaPagina({ aoQuadro }) {
    const camera = document.getElementById('camera');
    const video = document.getElementById('video');
    const canvas = document.getElementById('pontos');
    const aviso = document.getElementById('aviso-camera');
    const texto = document.getElementById('aviso-texto');
    const tentar = document.getElementById('tentar-camera');
    const mao = document.getElementById('indicador-mao');
    let temMao = null;

    function aoEstado(estado, mensagem) {
        aviso.dataset.estado = estado;
        aviso.hidden = estado === 'ao-vivo';
        texto.textContent = mensagem || TEXTOS_DO_AVISO[estado] || '';
        tentar.hidden = estado !== 'erro';
    }

    function aoQuadroDaCamera(quadro) {
        const agora = quadro.marcos !== null;
        if (agora !== temMao) {
            temMao = agora;
            mao.dataset.estado = agora ? 'sim' : 'nao';
            mao.querySelector('span').textContent = agora ? 'Mão detectada' : 'Sem mão';
        }
        aoQuadro(quadro);
    }

    function ligar() {
        ligarCameraMaos({
            video, canvas, modeloUrl: camera.dataset.modelo, aoEstado, aoQuadro: aoQuadroDaCamera,
        });
    }
    tentar.addEventListener('click', ligar);
    ligar();
    if (new URLSearchParams(location.search).has('diagnostico')) mostrarDiagnostico(camera);
}

/** Painel com FPS e tempos (abra a página com ?diagnostico=1). */
function mostrarDiagnostico(camera) {
    const painel = document.createElement('pre');
    painel.className = 'rc-diagnostico';
    camera.appendChild(painel);
    setInterval(() => {
        medidas.atualizar(performance.now());
        painel.textContent = [
            `detector: ${medidas.processador || '…'}  imagem: ${medidas.resolucao || '…'}`,
            `câmera: ${medidas.fpsCamera.toFixed(0)} fps   detector: ${medidas.fpsDeteccao.toFixed(0)} fps`,
            `detecção: ${medidas.msDeteccao.toFixed(1)} ms   desenho: ${medidas.msDesenho.toFixed(1)} ms`,
        ].join('\n');
    }, 500);
}
