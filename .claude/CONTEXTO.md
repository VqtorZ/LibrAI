# LibrAI — memória do projeto

Arquivo de contexto para retomar o trabalho (palavra-chave **RELEMBRE**).
Última atualização: **2026-10-06**.

---

## 1. Estado atual (onde paramos)

- **Branch de trabalho:** `melhorias-movimento` (enviado ao GitHub,
  `origin/melhorias-movimento`). Tem **14 commits que ainda não estão no
  `main`** (13 de código + o registro desta memória); o `main` está em
  `e61c9d3`. O merge (ou PR) espera a aprovação do
  usuário: https://github.com/VqtorZ/LibrAI/pull/new/melhorias-movimento
- **Testes:** 172 passando.
- **Sinais cadastrados (banco local `db.sqlite3`, fora do Git):**
  - `#2 J`, movimento: **26 amostras, todas de origem `opencv`** (gravadas pelo
    `gravar_movimento`, ~25–30 fps). As 5 amostras antigas do navegador foram
    apagadas pelo usuário.
  - `#3 Z`, movimento: **cadastrado, 0 amostras**.
  - Nenhum exemplo negativo gravado ainda.
- **Modelo de movimentos** (`models/movimentos.joblib`, versionado, formato 2):
  treinado em 2026-10-06T22:48Z, classe única `J` (26 amostras), limiar 0.766.
- **Modelo estático** (`models/libras_alphabet.joblib`): RandomForest de 400
  árvores; dataset `dataset/landmarks.csv` com 10.933 amostras de **21 letras**
  (ABCDEFGILMNOPQRSTUVWY). Faltam H, J, K, X e Z; em Libras, H, K e X também
  envolvem movimento (a validar com o usuário).
- **Resultado confirmado pelo usuário:** com as amostras gravadas pelo OpenCV,
  **o J é reconhecido ao vivo no `/reconhecer/`**.
- **Próximo passo combinado:** o usuário vai **gravar o Z pela página do site**
  (Gestos → Z → Gravar nova amostra) para testar a gravação web e o FPS novo.
  Depois, rodar `verificar_movimentos` (esperado ~25–30 fps nas amostras
  novas), `treinar_movimentos` e testar J vs Z ao vivo (ver Pendências).

---

## 2. O projeto

Aplicação **Django local** que reconhece Libras pela webcam usando OpenCV e os
21 marcos (landmarks) da mão do MediaPipe. São dois pipelines independentes:

- **Estático (alfabeto manual):** RandomForest classifica a letra frame a frame
  a partir das 63 coordenadas normalizadas + 10 distâncias entre pontas dos
  dedos. Coleta: `scripts/coletar_libras.py` (janela OpenCV, tecla S salva).
  Treino: `scripts/treinar_libras.py`.
- **Movimento (J, Z, gestos):** amostras temporais (sequências de landmarks)
  comparadas por DTW (vizinho mais próximo) com limiar de rejeição.

Ambiente: Windows 11, Python 3.11.9 em `.venv`, Django 5.2, mediapipe 0.10.21
(fixado: versões novas removeram `mp.solutions`), OpenCV 4.11, scikit-learn
1.9. Remoto: https://github.com/VqtorZ/LibrAI.git

Rodar: `.\.venv\Scripts\python.exe manage.py runserver` → http://127.0.0.1:8000/
(o terminal precisa ficar aberto; "ERR_CONNECTION_REFUSED" = servidor parado).

---

## 3. Arquitetura (arquivos e responsabilidades)

| Arquivo | Papel |
|---|---|
| `libras/vision.py` | Câmera do servidor (singleton `camera`). `abrir_camera()` (960×540, CAP_DSHOW) e `criar_detector_maos()` (modo vídeo, complexity 0, 0.65/0.6) são **a fonte única** de configuração. Stream MJPEG, classificação estática (limitada a cada 150 ms, `n_jobs=1`), detector de movimento ao vivo, gravação de amostras pela página (`iniciar_gravacao`/`parar_gravacao`), status JSON. Importável **sem Django** (os scripts do alfabeto usam): imports de Django são feitos sob demanda. |
| `libras/marcos.py` | Sem Django. `marcos_da_mao(result)` → (63 valores, "Right"/"Left") e `lateralidade()`. Usado por todos os caminhos de captura. |
| `libras/movimentos.py` | Persistência das amostras: `salvar_amostra(sinal, sequencia, origem="opencv")` grava JSON em `media/movimentos/<sinal>/<amostra>.json` + registro `AmostraMovimento`; `ler_sequencia` (com proteção de caminho); `apagar_amostra`. Formato JSON **versão 2** (cada frame tem `mao`); versão 1 continua aceita. |
| `libras/verificacao.py` | Verificador estrutural dos JSONs (Etapa 4.1): `verificar_conteudo` (sem banco) e `verificar_amostra` (confere com o banco). |
| `libras/temporal.py` | Pipeline temporal: segmentação, features, DTW, treino, calibração, previsão (detalhes na seção 4). |
| `libras/ao_vivo.py` | `DetectorMovimento`: recebe frames ao vivo, usa o `Segmentador`, avalia com o modelo quando a mão para, recarrega o modelo quando o arquivo muda e registra cada movimento no log (`libras.ao_vivo`). |
| `libras/gravacao.py` | `GravadorMovimento` (acumula frames, limite 30 s / 1200 frames, salva com origem "opencv") e `localizar_sinal` (por título sem diferenciar caixa ou por número). Usado pelo comando **e** pela página. |
| `libras/models.py` | `Sinal` (titulo, tipo ESTATICO/MOVIMENTO, **negativo**, descricao, ativo) e `AmostraMovimento` (metadados + caminho do JSON). Migrações até `0003_sinal_negativo`. |
| `libras/views.py` / `urls.py` | Páginas e rotas (abaixo). |
| `libras/management/commands/` | `verificar_movimentos`, `treinar_movimentos`, `testar_movimento`, `gravar_movimento`. |
| `templates/libras/` | `home`, `recognizer` (ao vivo), `gestos`, `gesto_form` (com checkbox "Exemplo negativo"), `gesto_detalhe`, `gravar` (estúdio de gravação). |
| `config/settings.py` | `LOGGING` mostra o logger `libras` (INFO) no terminal do runserver. |

**Rotas:** `/` · `/reconhecer/` · `/video/` (MJPEG) · `/api/status/` ·
`/gestos/` · `/gestos/novo/` · `/gestos/<id>/` · `/gestos/<id>/gravar/` ·
`POST /gestos/<id>/gravacao/iniciar/` · `POST /gestos/<id>/gravacao/parar/` ·
`POST /gestos/<id>/amostras/<amostra_id>/apagar/`.

`/api/status/` devolve: `label`, `error`, `model_ready`, `movement_ready`,
`movement_label`, `hand_detected`, `recording` (`ativa`, `sinal_id`,
`duracao_ms`, `no_limite`).

---

## 4. Pipeline de movimento (como funciona hoje)

1. **Captura** (sempre a câmera do servidor, mesmo caminho do reconhecimento):
   - página `/gestos/<id>/gravar/`: câmera com os 21 pontos, indicador "Mão
     detectada", **Espaço** inicia/para e salva (auto-salva aos 30 s);
   - terminal: `manage.py gravar_movimento <sinal>` (janela OpenCV, Espaço
     grava/para, Q/ESC sai). Só grava sinais já cadastrados como movimento.
   - Protocolo de gravação: configuração inicial com a mão **parada** (no J, o
     I), Espaço, movimento completo, mão parada, Espaço.
2. **Segmentação** (`temporal.Segmentador`, usada no treino **e** ao vivo):
   velocidade = norma da variação de [forma normalizada + pulso/tamanho da mão]
   por segundo, média de 3 frames. Começa com ≥ 6.0 u/s, termina após 350 ms
   abaixo de 4.0 u/s (ou sem mão, ou aos 4 s). Mínimo 400 ms de movimento;
   inclui 300 ms de contexto antes. Nas gravações, `trecho_principal` usa o
   movimento mais longo (descarta a mão entrando/saindo). Calibrado com dados
   reais: repouso ~1–3,5 u/s, movimento do J ~8–25 u/s.
3. **Features por passo** (`processar_frames`, 65 valores): 63 da forma da mão
   (relativa ao pulso e à escala) + 2 do **deslocamento do pulso** desde o
   início, em tamanhos de mão (pulso→base do dedo médio, mediana). Antes:
   lacunas interpoladas, mão esquerda espelhada (maioria dos frames "Left"),
   reamostragem a 66 ms (~15 fps); depois: aparo do repouso das pontas (15% da
   velocidade de pico).
4. **Classificação** (`prever`): vizinho mais próximo por DTW (custo
   euclidiano, normalizado por max(n, m)). Rejeita se a distância passar do
   limiar da classe **ou** se um exemplo negativo estiver mais perto.
5. **Limiar** (`_calibrar`): **mediana** das distâncias leave-one-out da classe
   × 1.5 (mínimo 0.05). Com exemplos negativos: no máximo o ponto médio entre a
   mediana e o negativo mais próximo; se houver sobreposição, volta à mediana e
   o treino avisa.
6. **Ao vivo** (`/reconhecer/`): enquanto a mão se move, a tela mostra
   "Analisando movimento…" (em vez do I); um movimento aceito aparece por
   2,5 s. O terminal do runserver registra cada movimento: duração, frames,
   distância, limiar e ACEITO/REJEITADO/ignorado com o motivo.
7. **Exemplos negativos:** sinais de movimento marcados como "Exemplo negativo"
   (ex.: "J incompleto", "I parado") não viram classe; só apertam a rejeição.

---

## 5. Decisões importantes e por quê (com evidências medidas)

- **Deslocamento do pulso nas features (formato 2):** a normalização antiga
  subtraía o pulso, descartando o movimento do braço (o pulso se desloca 1,2–1,8
  tamanhos de mão no J). O Z ficaria idêntico a uma mão parada apontando. Com o
  canal novo, um "Z simulado" passou a ser rejeitado como J.
- **Limiar pela mediana (não pelo máximo):** com 4–5 amostras, um par distante
  estourava o limiar (até 2,29) e o modelo aceitava mão parada. Avaliação
  honesta: mediana×1.5 aceitou 5/5 J e rejeitou 100% dos J invertidos, mãos
  paradas e Z simulados; o J pela metade caiu para 2/5.
- **Mesma segmentação no treino e ao vivo:** o replay das gravações reais pelo
  detector ao vivo foi de 3/5 para **5/5** J reconhecidos.
- **Causa do "J reconhecido como I":** as gravações antigas pelo navegador não
  mostravam os pontos; ~50% dos frames eram mão fora do quadro, porque a mão
  entrava, fazia o J e saía sem pausa. O modelo aprendeu "entrada + J + saída".
  Solução: `gravar_movimento` (janela com pontos, mão parada no início/fim). O
  usuário confirmou que o J passou a funcionar.
- **Um único caminho de captura (câmera do servidor):** a captura antiga pelo
  navegador (JPEG reduzido a 480 px, MediaPipe em modo foto) foi **removida**,
  porque gerava amostras diferentes do que o reconhecedor vê. Consequência
  aceita: **só grava quem está no computador do servidor**. Gravação remota
  exigiria MediaPipe no navegador (JS) + retreino de tudo — decisão adiada pelo
  usuário.
- **Resolução única 960×540:** o `coletar_libras.py` abria na resolução padrão
  da webcam, distorcendo a proporção dos landmarks em relação ao reconhecimento.
- **FPS do site:** o loop gastava ~100 ms/frame (~10 fps): RandomForest com
  `n_jobs=-1` = 48 ms por previsão (com `n_jobs=1`: 20 ms), classificação em
  todo frame e `sleep(0.03)` fixo. Corrigido (estimativa ~20 ms/frame → limite
  da webcam ~30 fps). **Ainda não validado ao vivo.**
- **Termo de pontas no DTW (testado e descartado):** comparar as poses de
  início/fim não separou o J incompleto e inflou a variação entre J reais.

---

## 6. Histórico

### Antes de 2026-10-06 (já no `main`)
Projeto inicial (A–D estáticos) → classificador RandomForest do alfabeto →
cadastro de sinais (`Sinal`) → tipo estático/movimento → coleta temporal pelo
navegador → Etapa 4.1 (verificador) → 4.2 (DTW experimental) → 4.3 (teste de
rejeição não-J com arquivo sintético `dataset/nao_j_sintetico.json`).

### 2026-10-06 (branch `melhorias-movimento`)
1. `fce1be8` lateralidade da mão por frame (formato JSON v2)
2. `ece0d1d` features v2: deslocamento do pulso, espelhamento, reamostragem,
   aparo de repouso
3. `99c877b` exemplos negativos (campo `Sinal.negativo`, migração 0003)
4. `fceaffc` reconhecimento de movimento ao vivo + segmentação compartilhada +
   limiar pela mediana
5. `1befff6` contagem regressiva na gravação web (depois substituída)
6. `b08b71b` README reescrito
7. `a790372` resolução 960×540 em todos os caminhos
8. `8c29ce9` comando `gravar_movimento` (OpenCV, com pontos visíveis)
9. `3bb0c34` diagnóstico no terminal + "Analisando movimento…"
10. `534a32d` README do `gravar_movimento`
11. `e35cbd8` página de gravação usa a câmera do servidor; captura pelo
    navegador removida
12. `e8ee910` modelo retreinado com 26 amostras de J (limiar 0.766)
13. `c53f4d8` FPS do site (n_jobs=1, classificação a cada 150 ms, sem sleep fixo)
14. memória do projeto em `.claude/` (`CLAUDE.md`, `CONTEXTO.md`, `/relembre`)

---

## 7. Pendências e próximos passos

1. **Gravar o Z pelo site** (sinal #3 já existe) — ~10 amostras; conferir o FPS
   delas com `verificar_movimentos` (esperado ~25–30) — isso valida a correção
   de FPS e a página de gravação, ambas **não testadas ao vivo**.
2. **Treinar com J + Z** e testar a confusão entre eles ao vivo (J não pode
   virar Z e vice-versa); pedir ao usuário as linhas do terminal do runserver.
3. **Merge do `melhorias-movimento` no `main`** (ou PR) — quando o usuário
   aprovar.
4. **Exemplos negativos:** gravar "J incompleto" / "I parado" (mecanismo pronto,
   nenhum gravado) — é o que resolve o J pela metade ainda aceito.
5. **Mais pessoas** gravando cada sinal (hoje os dados são de uma pessoa).
6. **Alfabeto estático (decisão do usuário):** o dataset antigo foi coletado na
   resolução padrão da webcam (desconhecida); a coleta agora é 960×540. O
   `coletar_libras.py` ainda usa `model_complexity` padrão (1) e confiança
   0.7/0.7, enquanto o reconhecedor usa complexity 0 e 0.65/0.6 — não alinhado
   de propósito (exigiria recoletar). H, K e X não estão no dataset.
7. **Melhoria possível:** com duas abas de câmera abertas, cada uma fica com
   metade do FPS (cada stream roda seu próprio loop). Uma thread única de
   captura compartilhada resolveria.

---

## 8. Comandos úteis

```powershell
.\.venv\Scripts\python.exe manage.py runserver
.\.venv\Scripts\python.exe manage.py gravar_movimento Z      # sinal precisa existir (tipo Movimento)
.\.venv\Scripts\python.exe manage.py verificar_movimentos     # integridade + fps das amostras
.\.venv\Scripts\python.exe manage.py treinar_movimentos
.\.venv\Scripts\python.exe manage.py testar_movimento --amostra <id>
.\.venv\Scripts\python.exe manage.py testar_movimento --arquivo dataset/nao_j_sintetico.json
.\.venv\Scripts\python.exe manage.py test libras
.\.venv\Scripts\python.exe scripts\coletar_libras.py          # alfabeto estático
.\.venv\Scripts\python.exe scripts\treinar_libras.py
```

**Conferir dados** (sinais, amostras por origem e modelo de movimentos):

```bash
.venv/Scripts/python.exe -c "
import os,django;os.environ['DJANGO_SETTINGS_MODULE']='config.settings';django.setup()
from libras.models import Sinal
from libras.movimentos import ler_sequencia
from libras import temporal
for s in Sinal.objects.all().order_by('pk'):
    ams=list(s.amostras.filter(ativo=True)); orig={}
    for a in ams:
        o=ler_sequencia(a).get('origem','navegador(antiga)'); orig[o]=orig.get(o,0)+1
    print(s.pk, s.titulo, s.tipo, 'negativo' if s.negativo else '', len(ams), orig)
m=temporal.carregar_modelo()
print(m['treinado_em'], m['amostras_por_classe'], {c: round(v,3) for c,v in m['limiares'].items()})
" 2>/dev/null
```

---

## 9. Notas para o Claude (ambiente e armadilhas)

- **Heredocs no Bash deste Windows quebram** com crases/`${...}` de JavaScript
  ("unexpected EOF"): escreva scripts de edição num arquivo (ferramenta Write,
  no scratchpad) e execute com o Python da `.venv`. Nas edições por script, use
  `assert texto.count(trecho) == 1` antes de substituir.
- A saída do terminal mostra acentos trocados quando passa por `grep`
  (só visual; os arquivos estão em UTF-8).
- Não abra a webcam pelas ferramentas do Claude: ela costuma estar em uso, e
  quem faz o gesto é o usuário. Para validar a lógica sem câmera há os testes,
  o replay das gravações pelo `DetectorMovimento` e frames sintéticos em
  `Camera._annotate`.
- `libras/vision.py` cria `camera = Camera()` na importação (carrega o
  MediaPipe); os scripts do alfabeto o importam sem Django — mantenha os imports
  de Django dentro de métodos.
- `db.sqlite3` e `media/` estão no `.gitignore` (as amostras de movimento não
  vão para o GitHub); `models/*.joblib` e `dataset/` são versionados.
- Privacidade: nenhum vídeo é armazenado, só landmarks. Se pessoas de fora forem
  gravar, lembrar o usuário de combinar consentimento.
