# LibrAI

Aplicação local em Django que reconhece sinais de Libras pela webcam usando
OpenCV e os 21 marcos da mão do MediaPipe. São dois pipelines independentes:

- **Sinais estáticos** (alfabeto manual): um classificador RandomForest
  reconhece a letra frame a frame.
- **Sinais com movimento** (como J e, futuramente, Z): amostras gravadas pelo
  site são comparadas por DTW (Dynamic Time Warping) com o movimento feito
  diante da câmera.

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
do reconhecimento é aberta pelo processo Python; permita o acesso nas
Configurações de Privacidade do Windows e feche aplicativos que já a estejam
usando.

## Alfabeto estático

```powershell
python scripts/coletar_libras.py   # faça o sinal e pressione S para salvar
python scripts/treinar_libras.py
```

Repita a coleta para cada letra, variando pessoas, mãos, iluminação e
distância. O modelo é salvo em `models/libras_alphabet.joblib` e carregado
automaticamente pela câmera.

## Sinais com movimento

### 1. Cadastrar e gravar

Em **Gestos → Cadastrar novo sinal**, escolha o tipo **Movimento** (ex.: `J`).
Na página do sinal, use **Gravar nova amostra**: após uma contagem de 3 s,
faça o movimento completo começando e terminando com a mão parada. O vídeo não
é armazenado; o servidor extrai apenas os marcos da mão de cada frame e salva a
sequência em `media/movimentos/<sinal>/<amostra>.json`, junto com a mão usada
(direita/esquerda).

Grave várias amostras por sinal, de preferência com pessoas diferentes.

### 2. Exemplos negativos

Para o modelo aprender onde um sinal *termina*, cadastre também movimentos
parecidos que **não** devem ser reconhecidos e marque **Exemplo negativo**
(ex.: "J incompleto", "I parado", movimentos de transição). Eles não viram
classe: apertam o limiar de rejeição e rejeitam entradas mais parecidas com
eles do que com o sinal real.

### 3. Verificar, treinar e testar

```powershell
python manage.py verificar_movimentos            # integridade das gravações
python manage.py treinar_movimentos              # gera models/movimentos.joblib
python manage.py testar_movimento --amostra 3    # testa uma gravação (leave-one-out)
python manage.py testar_movimento --arquivo dataset/nao_j_sintetico.json
```

Depois de treinar, o `/reconhecer/` passa a reconhecer o movimento ao vivo: faça
o sinal e pare a mão no final. O modelo é recarregado automaticamente quando é
retreinado.

### Como funciona

Cada gravação e cada movimento ao vivo passam pelo mesmo processamento
(`libras/temporal.py`):

1. **Segmentação por velocidade**: o movimento começa quando a mão acelera e
   termina quando ela para. Nas gravações, isso descarta a mão entrando e
   saindo do quadro.
2. **Features por passo**: a forma da mão relativa ao pulso (63 valores) e o
   deslocamento do pulso em "tamanhos de mão" (2 valores). O deslocamento é
   essencial para sinais em que o braço desenha o movimento, como o Z.
3. **Normalizações**: sinais feitos com a mão esquerda são espelhados, e a
   sequência é reamostrada a 15 fps para comparar gravação e câmera ao vivo.
4. **Classificação**: vizinho mais próximo por DTW, com limiar de rejeição
   calibrado pela distância típica (mediana) entre as amostras de cada sinal e
   ajustado pelos exemplos negativos.

## Limites

O reconhecimento de movimento é um protótipo: com poucas amostras de uma só
pessoa, ele demonstra que o pipeline reproduz o padrão gravado, não que
generaliza para qualquer pessoa. Antes de usar com o público, grave amostras de
pessoas diferentes e exemplos negativos, e acompanhe os relatórios de
`treinar_movimentos`. Libras inclui ainda expressões faciais, orientação e
contexto, que este projeto não cobre.
