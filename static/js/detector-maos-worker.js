// Detector de mão fora da página (Web Worker clássico).
//
// A análise de cada imagem (MediaPipe) leva dezenas de milissegundos em
// muitos computadores; rodando aqui, ela não trava o vídeo nem a página.
// Recebe imagens já reduzidas (ImageBitmap) e devolve os 21 pontos.
//
// Escolhe sozinho o mais rápido entre GPU e CPU nesta máquina: em algumas
// placas de vídeo integradas, o modo GPU do MediaPipe é o mais lento.

const VERSAO_MEDIAPIPE = '0.10.21';
const CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSAO_MEDIAPIPE}`;

// O pacote "cjs" funciona em worker clássico (o carregador do WebAssembly
// usa importScripts, que worker de módulo não tem). Fica no próprio site
// (vendor/, cópia idêntica do pacote oficial, licença Apache-2.0) porque o
// CDN o entrega como "application/node", e o navegador recusa.
self.module = { exports: {} };
self.exports = self.module.exports;
importScripts(`vendor/mediapipe-tasks-vision-${VERSAO_MEDIAPIPE}.js`);
const { FilesetResolver, HandLandmarker } = self.module.exports;

// Quantas análises descartar (aquecimento) e quantas medir em cada modo.
const AQUECIMENTO = 5;
const AMOSTRAS = 15;
// Abaixo disto a GPU já está boa: nem testa a CPU.
const GPU_SUFICIENTE_MS = 25;

let arquivos = null;
let modeloUrl = null;
let atual = null;     // { detector, processador, tempos: [] }
let candidato = null; // CPU em teste, enquanto a GPU continua atendendo
let decidido = false;
let ultimoInstante = -1;

async function criar(processador) {
    const detector = await HandLandmarker.createFromOptions(arquivos, {
        baseOptions: { modelAssetPath: modeloUrl, delegate: processador },
        runningMode: 'VIDEO',
        numHands: 1,
        minHandDetectionConfidence: 0.6,
        minHandPresenceConfidence: 0.6,
        minTrackingConfidence: 0.5,
    });
    return { detector, processador, tempos: [] };
}

function media(tempos) {
    const medidos = tempos.slice(AQUECIMENTO);
    return medidos.reduce((soma, t) => soma + t, 0) / medidos.length;
}

function avisarProcessador() {
    self.postMessage({ tipo: 'processador', processador: atual.processador });
}

async function testarCpu() {
    try {
        candidato = await criar('CPU');
    } catch (falha) {
        decidido = true; // sem CPU disponível: fica com a GPU
    }
}

function detectar(motor, imagem, instante) {
    const inicio = performance.now();
    const resultado = motor.detector.detectForVideo(imagem, instante);
    const ms = performance.now() - inicio;
    if (motor.tempos.length < AQUECIMENTO + AMOSTRAS) motor.tempos.push(ms);
    return { resultado, ms };
}

function decidir() {
    if (decidido || atual.tempos.length < AQUECIMENTO + AMOSTRAS) return;
    if (atual.processador === 'GPU' && !candidato) {
        if (media(atual.tempos) <= GPU_SUFICIENTE_MS) {
            decidido = true;
        } else {
            testarCpu();
        }
        return;
    }
    if (candidato && candidato.tempos.length >= AQUECIMENTO + AMOSTRAS) {
        decidido = true;
        if (media(candidato.tempos) < media(atual.tempos)) {
            atual.detector.close();
            atual = candidato;
            avisarProcessador();
        } else {
            candidato.detector.close();
        }
        candidato = null;
    }
}

async function iniciar(dados) {
    modeloUrl = dados.modeloUrl;
    arquivos = await FilesetResolver.forVisionTasks(`${CDN}/wasm`);
    try {
        atual = await criar('GPU');
    } catch (falha) {
        atual = await criar('CPU');
        decidido = true;
    }
    self.postMessage({ tipo: 'pronto', processador: atual.processador });
}

function analisar({ imagem, instante }) {
    let resposta = { tipo: 'resultado', instante, pontos: null, lado: null, ms: 0 };
    try {
        if (instante <= ultimoInstante) { // o MediaPipe exige tempo crescente
            resposta.ignorado = true;
            return;
        }
        ultimoInstante = instante;
        const { resultado, ms } = detectar(atual, imagem, instante);
        // Enquanto mede a CPU, ela analisa a mesma imagem (só para medir).
        if (candidato && candidato.tempos.length < AQUECIMENTO + AMOSTRAS) detectar(candidato, imagem, instante);
        decidir();
        const pontos = resultado.landmarks && resultado.landmarks[0];
        const lado = resultado.handedness && resultado.handedness[0] && resultado.handedness[0][0];
        resposta = {
            tipo: 'resultado',
            instante,
            pontos: pontos ? pontos.map((p) => [p.x, p.y, p.z]) : null,
            lado: lado ? lado.categoryName : null,
            ms,
        };
    } catch (falha) {
        resposta.erro = String(falha && falha.message || falha);
    } finally {
        imagem.close();
        self.postMessage(resposta);
    }
}

self.onmessage = async (evento) => {
    const dados = evento.data;
    if (dados.tipo === 'iniciar') {
        try {
            await iniciar(dados);
        } catch (falha) {
            self.postMessage({ tipo: 'erro', mensagem: String(falha && falha.message || falha) });
        }
    } else if (dados.tipo === 'quadro') {
        analisar(dados);
    }
};
