# LibrAI

Aplicação local em Django que reconhece sinais de Libras pela webcam usando
OpenCV e os 21 marcos da mão do MediaPipe. São dois pipelines independentes:

- **Alfabeto estático:** um classificador RandomForest reconhece a letra frame
  a frame.
- **Sinais com movimento** (como J e Z): amostras gravadas são comparadas por
  DTW (Dynamic Time Warping) com o movimento feito diante da câmera.

## Mapa do projeto

```
OpenCV-Libras/
├── config/                  configurações do Django (settings, urls)
├── libras/                  o app
│   ├── caminhos.py          ONDE FICA CADA DADO (fonte única dos caminhos)
│   ├── captura/             câmera do servidor e leitura dos pontos da mão
│   │   ├── camera.py        transmissão, letra estática, movimento ao vivo, gravação
│   │   └── marcos.py        63 valores da mão + mão direita/esquerda
│   ├── estatico/            alfabeto estático
│   │   ├── features.py      como a mão vira números (coordenadas + distâncias)
│   │   └── treino.py        treino do RandomForest
│   ├── movimento/           sinais com movimento, na ordem do fluxo:
│   │   ├── gravacao.py      grava a amostra pela câmera
│   │   ├── amostras.py      salva/lê o JSON da amostra
│   │   ├── verificacao.py   confere se as gravações estão íntegras
│   │   ├── segmentacao.py   recorta o trecho em que a mão se moveu
│   │   ├── trajetoria.py    transforma os frames em números comparáveis
│   │   ├── classificador.py DTW: treino, limiar de rejeição e previsão
│   │   └── ao_vivo.py       reconhecimento na câmera do /reconhecer/
│   ├── management/commands/ todos os comandos do manage.py (abaixo)
│   ├── tests/               testes divididos por área
│   └── models.py, views.py, urls.py, forms.py, admin.py
├── dados/                   TODOS OS DADOS
│   ├── banco.sqlite3                      banco (sinais e registro das amostras) — só local
│   ├── amostras_estaticas/landmarks.csv   amostras do alfabeto (letra + 63 números por linha)
│   ├── amostras_movimento/<id>-<sinal>/   uma amostra de movimento por JSON (ex.: 2-j/7.json) — só local
│   ├── modelos_treinados/                 alfabeto.joblib e movimentos.joblib
│   └── sinteticos/                        dados artificiais de teste (nunca entram no treino)
├── templates/libras/        páginas (inicio, reconhecer, gestos, gravar…)
└── static/                  CSS e imagens
```

O banco e as gravações de movimento (`dados/banco.sqlite3` e
`dados/amostras_movimento/`) **não vão para o GitHub**: para ter uma cópia de
segurança, copie os dois juntos.

## Executar no Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Abra `http://127.0.0.1:8000/` e selecione **Iniciar reconhecimento**. A câmera
é aberta pelo processo Python; permita o acesso nas Configurações de
Privacidade do Windows e feche aplicativos que já a estejam usando. Só uma
página (ou comando) por vez consegue usar a câmera.

## Acesso

A home e o **Reconhecer** são livres para todos. A área de **Gestos** (cadastrar,
gravar, apagar, excluir e treinar) é só para administradores: entre em
**Entrar** (`/entrar/`) com o e-mail e a senha. Contas são criadas pelo
terminal, com a senha digitada na hora (nunca fica em arquivo):

```powershell
python manage.py criar_admin pessoa@exemplo.com --nome Pessoa
python manage.py criar_admin voce@exemplo.com --nome Você --master
```

A conta **master** também gerencia os usuários (trocar senha, desativar) no
painel do Django em `/admin/`.

## Comandos

| Comando | O que faz |
|---|---|
| `python manage.py coletar_alfabeto A` | Coleta amostras de uma letra estática (S salva, Q sai) |
| `python manage.py treinar_alfabeto` | Treina o classificador do alfabeto |
| `python manage.py gravar_movimento J` | Grava amostras de um sinal de movimento (Espaço grava/para, Q sai) |
| `python manage.py verificar_movimentos` | Confere a integridade e o FPS das gravações |
| `python manage.py treinar_movimentos` | Treina o reconhecimento de movimentos |
| `python manage.py testar_movimento --amostra 7` | Testa uma gravação (sem ela no modelo) |
| `python manage.py testar_movimento --arquivo dados/sinteticos/nao_j_sintetico.json` | Testa a rejeição de um movimento que não é J |
| `python manage.py gerar_nao_j_sintetico` | Recria o arquivo sintético não-J |
| `python manage.py criar_admin email --nome Nome [--master]` | Cria ou atualiza uma conta de administrador |
| `python manage.py test libras` | Roda os testes |

## Alfabeto estático

Colete cada letra variando pessoas, mãos, iluminação e distância, e treine:

```powershell
python manage.py coletar_alfabeto A
python manage.py treinar_alfabeto
```

O modelo é carregado pela câmera ao iniciar o servidor (reinicie o
`runserver` depois de treinar). A coleta usa a mesma resolução do
reconhecimento (960×540).

## Sinais com movimento

### 1. Cadastrar e gravar

Em **Gestos → Cadastrar novo sinal**, escolha o tipo **Movimento** (ex.: `J`).
Depois grave as amostras de um destes dois jeitos — os dois usam a mesma câmera,
resolução e detector do reconhecimento ao vivo, então as amostras saem como o
reconhecedor as verá:

- **Pelo site:** na página do sinal, **Gravar nova amostra**. A câmera aparece
  com os 21 pontos da mão e um indicador de "Mão detectada".
- **Pelo terminal** (com o site fechado, para liberar a câmera):
  `python manage.py gravar_movimento J`.

Nos dois, faça a configuração inicial com a mão parada (no J, o I), aperte
**Espaço**, faça o movimento, pare a mão e aperte **Espaço** de novo; a amostra
é salva na hora. O comando só grava sinais já cadastrados como movimento.

A câmera é a do computador onde o servidor está rodando: quem for gravar
precisa estar nele. O vídeo nunca é armazenado — só os pontos da mão, com a mão
usada (direita/esquerda) e a origem da captura. Grave várias amostras por
sinal, de preferência com pessoas diferentes.

### 2. Exemplos negativos

Para o modelo aprender onde um sinal *termina*, cadastre também movimentos
parecidos que **não** devem ser reconhecidos e marque **Exemplo negativo**
(ex.: "J incompleto", "I parado"). Eles não viram classe: apertam o limiar de
rejeição e rejeitam entradas mais parecidas com eles do que com o sinal real.

### 3. Verificar, treinar e testar

Rode `verificar_movimentos`, `treinar_movimentos` e `testar_movimento` (ver
**Comandos**). Depois de treinar, o `/reconhecer/` reconhece o movimento ao
vivo: faça o sinal e pare a mão no final. Enquanto a mão se move, a tela mostra
"Analisando movimento…". O modelo é recarregado sozinho quando é retreinado, e
o terminal do `runserver` registra cada movimento com a distância, o limiar e
o motivo de ter sido aceito, rejeitado ou ignorado.

### Como funciona

Cada gravação e cada movimento ao vivo passam pelo mesmo processamento
(`libras/movimento/`):

1. **Segmentação por velocidade** (`segmentacao.py`): o movimento começa
   quando a mão acelera e termina quando ela para. Nas gravações, isso descarta
   a mão entrando e saindo do quadro.
2. **Trajetória** (`trajetoria.py`): a forma da mão relativa ao pulso (63
   valores) e o deslocamento do pulso em "tamanhos de mão" (2 valores) — este é
   essencial para sinais em que o braço desenha o movimento, como o Z. Sinais
   feitos com a mão esquerda são espelhados, e tudo é reamostrado a 15 fps.
3. **Classificação** (`classificador.py`): vizinho mais próximo por DTW, com
   limiar de rejeição calibrado pela distância típica (mediana) entre as
   amostras de cada sinal e ajustado pelos exemplos negativos.

## Limites

O reconhecimento de movimento é um protótipo: com poucas amostras de uma só
pessoa, ele demonstra que o pipeline reproduz o padrão gravado, não que
generaliza para qualquer pessoa. Antes de usar com o público, grave amostras de
pessoas diferentes e exemplos negativos, e acompanhe os relatórios de
`treinar_movimentos`. Libras inclui ainda expressões faciais, orientação e
contexto, que este projeto não cobre.
