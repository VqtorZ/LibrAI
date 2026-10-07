# LibrAI

Aplicação Django que reconhece sinais de Libras pela webcam usando os 21
marcos da mão do MediaPipe. A câmera é a do **navegador** de quem usa o site: o
MediaPipe roda ali mesmo e só os pontos da mão vão para o servidor (a imagem
nunca sai do aparelho). Por isso o site pode ficar na internet e cada pessoa
usa a própria webcam. São dois pipelines independentes:

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
│   ├── estatico/            alfabeto estático
│   │   ├── amostras.py      CSV das amostras gravadas pelo site
│   │   ├── features.py      como a mão vira números (coordenadas + distâncias)
│   │   ├── treino.py        treino do RandomForest
│   │   └── classificador.py letra ao vivo (recarrega o modelo sozinho)
│   ├── movimento/           sinais com movimento, na ordem do fluxo:
│   │   ├── amostras.py      valida os quadros do navegador e salva/lê o JSON
│   │   ├── verificacao.py   confere se as gravações estão íntegras
│   │   ├── segmentacao.py   recorta o trecho em que a mão se moveu
│   │   ├── trajetoria.py    transforma os frames em números comparáveis
│   │   ├── classificador.py DTW: treino, limiar de rejeição e previsão
│   │   ├── ao_vivo.py       detector de movimento quadro a quadro
│   │   └── sessoes.py       uma sessão ao vivo por aba do navegador
│   ├── management/commands/ todos os comandos do manage.py (abaixo)
│   ├── tests/               testes divididos por área
│   └── models.py, views.py, urls.py, forms.py, admin.py
├── dados/                   TODOS OS DADOS
│   ├── banco.sqlite3                      banco (sinais e registro das amostras) — só local
│   ├── amostras_estaticas/alfabeto.csv    amostras do alfabeto (letra + 63 números por linha)
│   ├── amostras_movimento/<id>-<sinal>/   uma amostra de movimento por JSON (ex.: 2-j/7.json) — só local
│   ├── modelos_treinados/                 alfabeto.joblib e movimentos.joblib
│   ├── legado/                            dados do tempo da câmera do servidor (fora dos treinos)
│   └── sinteticos/                        dados artificiais de teste (nunca entram no treino)
├── templates/libras/        páginas (inicio, reconhecer, gestos, gravar…)
└── static/                  CSS, imagens, js/camera-maos.js e o modelo do MediaPipe (modelos/)
```

O banco, as amostras e os modelos treinados **não vão para o GitHub**: com o
site no ar, eles nascem no servidor. Cópia de segurança de tudo num .zip:
`python manage.py backup_dados`.

## Publicar (site no ar)

O passo a passo para o PythonAnywhere (grátis) está em
[`docs/publicar-pythonanywhere.md`](docs/publicar-pythonanywhere.md). No
servidor, um arquivo `.env` (fora do Git) liga o modo produção
(`LIBRAI_PRODUCAO=1`, `LIBRAI_SECRET_KEY`, `LIBRAI_HOSTS`); localmente nada
muda. Com o site no ar, o login bloqueia por 15 minutos depois de 5 senhas
erradas, e senhas novas precisam de 10+ caracteres.

## Executar no Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Abra `http://127.0.0.1:8000/` e vá em **Reconhecer**. O navegador pede
permissão para usar a câmera: aceite. O navegador só libera a câmera em
`localhost` ou em sites `https`. O detector de mão (MediaPipe Tasks Vision) é
baixado de um CDN na primeira visita, então é preciso internet.

### Formato dos dados (versão 3)

Os pontos vêm espelhados como numa selfie, com x e z corrigidos pela proporção
da imagem, para que webcams diferentes deem os mesmos números para o mesmo
gesto. Amostras e modelos gravam a versão do formato; os da época da câmera do
servidor (versões 1 e 2) ficam guardados, mas fora dos treinos, e a página do
sinal pede para regravá-lo.

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
| `python manage.py treinar_alfabeto` | Treina o classificador do alfabeto |
| `python manage.py verificar_movimentos` | Confere a integridade e o FPS das gravações |
| `python manage.py treinar_movimentos` | Treina o reconhecimento de movimentos |
| `python manage.py testar_movimento --amostra 7` | Testa uma gravação (sem ela no modelo) |
| `python manage.py testar_movimento --arquivo dados/sinteticos/nao_j_sintetico.json` | Testa a rejeição de um movimento que não é J |
| `python manage.py gerar_nao_j_sintetico` | Recria o arquivo sintético não-J |
| `python manage.py criar_admin email --nome Nome [--master]` | Cria ou atualiza uma conta de administrador |
| `python manage.py backup_dados` | Gera `backups/librai-<data>.zip` com banco, amostras e modelos |
| `python manage.py test libras` | Roda os testes |

## Alfabeto estático

Em **Gestos → Gravar letras**, escolha a letra, faça o sinal e aperte
**Espaço** para salvar cada amostra. Varie pessoas, mãos, iluminação e
distância. Depois clique em **Treinar alfabeto** (ou rode
`python manage.py treinar_alfabeto`). O reconhecimento recarrega o modelo
sozinho, sem reiniciar o servidor.

## Sinais com movimento

### 1. Cadastrar e gravar

Em **Gestos → Cadastrar novo sinal**, escolha o tipo **Movimento** (ex.: `J`).
Depois, na página do sinal, clique em **Gravar nova amostra**. A câmera
aparece com os 21 pontos da mão e um indicador de "Mão detectada". É o mesmo
detector do reconhecimento ao vivo, então as amostras saem como o reconhecedor
as verá. Faça a configuração inicial com a mão parada (no J, o I), aperte
**Espaço**, faça o movimento, pare a mão e aperte **Espaço** de novo; a amostra
é salva na hora.

Cada pessoa grava da própria casa, com a própria webcam. O vídeo nunca sai do
navegador: só os pontos da mão são enviados, com a mão usada
(direita/esquerda). Grave várias amostras por sinal, de preferência com
pessoas diferentes.

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
o log do servidor registra cada movimento com a distância, o limiar e
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
