# LibrAI — memória do projeto

Arquivo de contexto para retomar o trabalho (palavra-chave **RELEMBRE**).
Última atualização: **2026-10-06**.

---

## 1. Estado atual (onde paramos)

- **Branch de trabalho:** `melhorias-movimento` (enviado ao GitHub,
  `origin/melhorias-movimento`). Tem **29 commits que ainda não estão no
  `main`** (o `main` está em `e61c9d3`). O merge (ou PR) espera a aprovação do
  usuário: https://github.com/VqtorZ/LibrAI/pull/new/melhorias-movimento
- **Testes:** 220 passando (`libras/tests/`, divididos por área).
- **Estrutura reorganizada em 2026-10-06** (seção 3): dados em `dados/`, código
  em `libras/captura/`, `libras/estatico/`, `libras/movimento/`; `scripts/` não
  existe mais (tudo via `manage.py`). Backup local de antes da reorganização
  (banco + 26 gravações + CSV) em `backups/antes-reorganizacao-2026-10-06/`,
  fora do Git — pode ser apagado quando o usuário quiser.
- **Sinais cadastrados (`dados/banco.sqlite3`, fora do Git):**
  - `#2 J`, movimento: **26 amostras, todas de origem `opencv`** (~27 fps), em
    `dados/amostras_movimento/2-j/`. As 5 amostras antigas do navegador foram
    apagadas pelo usuário.
  - `#3 Z`, movimento: **20 amostras gravadas pelo site** (~25 fps — confirma
    a correção de FPS do site; antes ficaria ~10).
  - Nenhum exemplo negativo gravado ainda.
- **Modelo de movimentos** (`dados/modelos_treinados/movimentos.joblib`,
  versionado, formato 2, salvo comprimido): treinado pelo usuário no site em
  2026-10-07T02:57Z com **J (26 amostras, limiar 0.766) e Z (20, limiar
  0.889)**, sem negativos.
- **Alfabeto estático — RECOMEÇANDO DO ZERO (2026-10-07):** a pedido do
  usuário, **todas as amostras do CSV foram apagadas** (9.579 de 19 letras,
  inclusive I e R recém-gravadas pelo site); `dados/amostras_estaticas/landmarks.csv`
  tem só o cabeçalho. Backups: `backups/antes-apagar-FTIR-2026-10-07/` e
  `backups/antes-apagar-alfabeto-2026-10-07/` (fora do Git; o histórico do Git
  também guarda o CSV antigo). O usuário vai **regravar todas as letras pelo
  site** (Gestos → Gravar letras). O modelo `alfabeto.joblib` (comprimido) é o
  último treinado pelo usuário: reconhece 19 letras (ABCDEGILMNOPQRSUVWY) e segue
  em uso até o próximo treino. Treinar com poucas letras gravadas faz as outras
  deixarem de ser reconhecidas — gravar todas antes de treinar.
- **Resultado confirmado pelo usuário:** com as amostras gravadas pelo OpenCV,
  **o J é reconhecido ao vivo no `/reconhecer/`**.
- **Front renovado em 2026-10-06** (seção 3): home nova (público principal:
  pessoas surdas — visual, frases curtas, animações suaves sem piscar, dados
  reais do sistema), botão "Treinar reconhecimento" no site, situação de cada
  sinal ("No reconhecimento" / "Precisa treinar"), página do sinal com resumo
  e tabela, menu marcando a página atual. Visual conferido por prints (Chrome
  headless) e **aprovado pelo usuário** ("ficou perfeito").
- **Página Reconhecer renovada** (mesma linguagem da home): estados visuais com
  cor/símbolo/frase, indicador "Mão detectada", selo do resultado sobre a
  câmera (removido a pedido do usuário: poluía o vídeo), "Soletrando" (forma palavras; letra parada fica provisória até o
  próximo sinal e é descartada se um movimento for reconhecido — evita "IJ";
  pose final de um movimento é ignorada por 1,5 s), dicas em cartões e a grade
  do alfabeto com dados reais. Conferida por prévias estáticas (template real
  + quadro simulado + status roteirizado), **não testada com a webcam**.
- **Gravar alfabeto pelo site** (2026-10-07): `/gestos/alfabeto/` — escolhe a
  letra (clique ou tecla), Espaço salva 1 amostra no CSV, "Desfazer última",
  "O LibrAI vê agora", botão Treinar alfabeto (~2,6 s). Usa a câmera e o
  detector do reconhecimento ao vivo (o `coletar_alfabeto` usa outra config do
  MediaPipe — pendência 6). A câmera recarrega o modelo do alfabeto sozinha
  quando o arquivo muda; treinos salvam o modelo de forma atômica.
- **Próximo passo combinado:** o usuário vai **regravar todo o alfabeto** pelo
  site e depois treinar. Oferecido e ainda não decidido: botão de gravação em
  rajada (vários quadros espaçados por Espaço).
  Também testar J vs Z ao vivo (Z já treinado).

---

## 2. O projeto

Aplicação **Django local** que reconhece Libras pela webcam usando OpenCV e os
21 marcos (landmarks) da mão do MediaPipe. São dois pipelines independentes:

- **Estático (alfabeto manual):** RandomForest classifica a letra frame a frame
  a partir das 63 coordenadas normalizadas + 10 distâncias entre pontas dos
  dedos. Coleta: `manage.py coletar_alfabeto <letra>` (janela OpenCV, S salva).
  Treino: `manage.py treinar_alfabeto`.
- **Movimento (J, Z, gestos):** amostras temporais (sequências de landmarks)
  comparadas por DTW (vizinho mais próximo) com limiar de rejeição.

Ambiente: Windows 11, Python 3.11.9 em `.venv`, Django 5.2, mediapipe 0.10.21
(fixado: versões novas removeram `mp.solutions`), OpenCV 4.11, scikit-learn
1.9. Remoto: https://github.com/VqtorZ/LibrAI.git

Rodar: `.\.venv\Scripts\python.exe manage.py runserver` → http://127.0.0.1:8000/
(o terminal precisa ficar aberto; "ERR_CONNECTION_REFUSED" = servidor parado).

---

## 3. Arquitetura (pastas e responsabilidades)

O README tem o mapa completo em árvore. Resumo:

**Dados — `dados/`** (caminhos definidos só em `libras/caminhos.py`, que também
é usado pelo `config/settings.py`):

| Caminho | Conteúdo | Git |
|---|---|---|
| `dados/banco.sqlite3` | banco do Django (sinais + registro das amostras) | não |
| `dados/amostras_estaticas/landmarks.csv` | alfabeto: letra + 63 coordenadas por linha | sim |
| `dados/amostras_movimento/<id>-<slug do título>/<amostra>.json` | uma amostra de movimento por arquivo (MEDIA_ROOT); o caminho de cada uma fica salvo no banco (`AmostraMovimento.arquivo_dados`) | não |
| `dados/modelos_treinados/` | `alfabeto.joblib`, `movimentos.joblib` (salvos com `compress=3`) | sim |
| `dados/sinteticos/nao_j_sintetico.json` | dado artificial do teste de rejeição | sim |

**Código — `libras/`:**

| Arquivo | Papel |
|---|---|
| `caminhos.py` | Fonte única dos caminhos de dados (sem Django). |
| `captura/camera.py` | Câmera do servidor (singleton `camera`). `abrir_camera()` (960×540, CAP_DSHOW) e `criar_detector_maos()` (modo vídeo, complexity 0, 0.65/0.6) são **a fonte única** de configuração da câmera. Stream MJPEG, letra estática (classificada no máximo a cada 150 ms, `n_jobs=1`), detector de movimento ao vivo, gravação pela página (`iniciar_gravacao`/`parar_gravacao`), status JSON. Imports de `movimento` (que dependem do Django) são feitos sob demanda dentro dos métodos. Nomes internos da classe `Camera` (classify, frames, status, last_label) e as chaves do JSON de status continuam em inglês (contrato com o JS das páginas). |
| `captura/marcos.py` | Sem Django. `marcos_da_mao(result)` → (63 valores, "Right"/"Left") e `lateralidade()`. |
| `estatico/features.py` | `extrair_features` (63 coords relativas ao pulso + 10 distâncias) e `features_geometricas`. Usado por coleta, treino e câmera. |
| `estatico/amostras.py` | CSV do alfabeto: `salvar` (63 coords normalizadas, igual à coleta), `contar`, `desfazer` (só a última linha), `LETRAS_ESTATICAS` (A–Z sem J e Z). Caminho lido na hora da chamada (testes redirecionam `AMOSTRAS_ESTATICAS`). |
| `estatico/treino.py` | `treinar(dataset, destino)` do RandomForest (mesmos parâmetros de sempre, `random_state=42`) e `montar_features`. |
| `movimento/amostras.py` | Persistência: `salvar_amostra(sinal, sequencia, origem="opencv")`, `ler_sequencia` (com proteção de caminho), `apagar_amostra`, `pasta_do_sinal` (`<id>-<slug>`). Formato JSON **versão 2** (cada frame tem `mao`); versão 1 continua aceita. |
| `movimento/verificacao.py` | Verificador estrutural dos JSONs: `verificar_conteudo` (sem banco) e `verificar_amostra` (confere com o banco). |
| `movimento/segmentacao.py` | `Segmentador` (início/fim do movimento por velocidade), `recortar`, `segmentos`, `trecho_principal`. |
| `movimento/trajetoria.py` | `normalizar_frame`, `processar_frames` (forma + deslocamento do pulso, espelhamento, reamostragem, aparo de repouso). |
| `movimento/classificador.py` | `distancia_dtw`, `treinar`, `_calibrar`/limiares, `carregar_modelo`, `prever`, `processar_sequencia`, `testar_amostra`, `testar_arquivo`, `ErroTemporal`, `MODELO_PATH`. |
| `movimento/ao_vivo.py` | `DetectorMovimento`: frames ao vivo → segmentação → previsão quando a mão para; recarrega o modelo quando o arquivo muda; log `libras.movimento.ao_vivo`. |
| `movimento/gravacao.py` | `GravadorMovimento` (limite 30 s / 1200 frames, origem "opencv") e `localizar_sinal`. Usado pelo comando **e** pela página. |
| `models.py` | `Sinal` (titulo, tipo ESTATICO/MOVIMENTO, **negativo**, descricao, ativo) e `AmostraMovimento` (metadados + caminho do JSON). Migrações até `0003_sinal_negativo`. |
| `views.py` / `urls.py` | Views `inicio`, `reconhecer`, `video`, `status`, `gestos`, `gesto_*`; nomes de rota iguais aos das views. |
| `contexto.py` | Context processor `versao_estaticos`: os links de CSS levam `?v=<mtime>`, para o navegador não usar cópia velha (o runserver não manda cabeçalhos de cache). |
| `management/commands/` | `coletar_alfabeto`, `treinar_alfabeto`, `gravar_movimento`, `verificar_movimentos`, `treinar_movimentos`, `testar_movimento`, `gerar_nao_j_sintetico`. |
| `tests/` | `base.py` (bases e auxiliares) + `test_sinais`, `test_amostras`, `test_classificador`, `test_ao_vivo`, `test_gravacao`, `test_camera`, `test_alfabeto`. |
| `templates/libras/` | `inicio` (home: dados reais da view, mão animada `_mao_svg`), `reconhecer` (ao vivo), `gestos` (lista com amostras + situação + aviso de treino), `gesto_form` ("Exemplo negativo" só aparece para Movimento), `gesto_detalhe` (resumo + tabela), `gravar`, `_cabecalho` (página atual, "Pular para o conteúdo"), `_botao_treinar` (POST `treinar_movimentos`, mostra "Treinando…"). |
| `static/css/` | `app.css` (geral; seções 16–17 = componentes e Gestos; 18 = `.etiqueta` e grade `.alfabeto-*`, usadas na home e no reconhecer), `home.css` (só a home) e `reconhecer.css` (só o reconhecer, classes `rc-*`). A página de gravação ainda usa os estilos antigos `.recognizer-layout`/`.recognition-panel`. CSS da home antiga foi removido. Regra global `[hidden] { display: none !important }`. Animações respeitam `prefers-reduced-motion`; `.reveal` só esconde com a classe `.js` no `<html>`. |
| `config/settings.py` | `LOGGING` mostra o logger `libras` (INFO) no terminal do runserver. |

**Rotas:** `/` · `/reconhecer/` · `/video/` (MJPEG) · `/api/status/` ·
`/gestos/` · `/gestos/novo/` · `POST /gestos/treinar/` · `/gestos/alfabeto/` ·
`POST /gestos/alfabeto/amostras/` · `POST /gestos/alfabeto/desfazer/` ·
`POST /gestos/alfabeto/treinar/` · `/gestos/<id>/` · `/gestos/<id>/gravar/` ·
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
2. **Segmentação** (`movimento/segmentacao.py`, usada no treino **e** ao vivo):
   velocidade = norma da variação de [forma normalizada + pulso/tamanho da mão]
   por segundo, média de 3 frames. Começa com ≥ 6.0 u/s, termina após 350 ms
   abaixo de 4.0 u/s (ou sem mão, ou aos 4 s). Mínimo 400 ms de movimento;
   inclui 300 ms de contexto antes. Nas gravações, `trecho_principal` usa o
   movimento mais longo (descarta a mão entrando/saindo). Calibrado com dados
   reais: repouso ~1–3,5 u/s, movimento do J ~8–25 u/s.
3. **Features por passo** (`movimento/trajetoria.py`, 65 valores): 63 da forma da mão
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
- **Sem bases de dados externas, por ora (decisão do usuário, 2026-10-06):**
  avaliamos MINDS-Libras, V-Librasil, LIBRAS-UFOP e o alfabeto da Mendeley. O
  usuário verificou e decidiu não usar nenhuma no momento: o projeto deve usar
  apenas sinais brasileiros (Libras) e ele encontrou sinais de outras línguas
  nessas bases. Os dados continuam vindo só das gravações próprias. Não
  voltar a sugerir essas bases sem que o usuário peça.

---

## 6. Histórico

### Antes de 2026-10-06 (já no `main`)
Projeto inicial (A–D estáticos) → classificador RandomForest do alfabeto →
cadastro de sinais (`Sinal`) → tipo estático/movimento → coleta temporal pelo
navegador → Etapa 4.1 (verificador) → 4.2 (DTW experimental) → 4.3 (teste de
rejeição não-J com arquivo sintético, hoje em `dados/sinteticos/nao_j_sintetico.json`).

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
15. registro da decisão de não usar bases externas e do plano de
    auto-aperfeiçoamento (só documentação)
16. `3db6105` dados reunidos em `dados/` (`libras/caminhos.py`), 26 amostras
    migradas para `2-j/`, modelos comprimidos (alfabeto 42,9 → 5,7 MB)
17. `f6e5d51` código em `captura/`, `estatico/`, `movimento/` (temporal.py
    dividido em segmentacao/trajetoria/classificador); scripts viram comandos
    (`coletar_alfabeto`, `treinar_alfabeto`, `gerar_nao_j_sintetico`); testes
    divididos em `libras/tests/` (180). Retreinos pelo código novo deram
    resultados idênticos aos modelos atuais.
18. nomes em português (views/rotas/templates `inicio`, `reconhecer`,
    `video`, `_cabecalho`), README com mapa do projeto, esta memória
19. `36daa54` CSS: o espaço do header fixo (76 px) passa a ser reservado no
    `body` de todas as páginas (o título de Gestos ficava sob o header) e
    `[id] { scroll-margin-top }` para os links do menu da home
20. memória atualizada com a correção do header
21. front renovado: home nova (`home.css`, `_mao_svg`), treino pelo site
    (`treinar_movimentos`, `classificador.situacao_dos_sinais`), páginas de
    Gestos com contagem/situação/resumo/tabela, menu com página atual, CSS
    versionado (`contexto.py`), CSS morto removido; 200 testes
22. memória com o front renovado e o Z gravado
23. página Reconhecer renovada (`reconhecer.css`, estados, Soletrando),
    componentes `.etiqueta`/`.alfabeto-*` compartilhados, `views._alfabeto()`;
    203 testes
24. (mesmo commit da memória) + reconhecer: sem o selo dentro da câmera
    (pedido do usuário) e câmera maior — página com 1380 px, coluna da câmera
    2fr × painel .82fr (+38% a 1440 px), topo compacto e, em telas largas,
    largura limitada pela altura da tela para o vídeo caber inteiro
25. modelo J+Z (treinado pelo usuário) e remoção das amostras F/T/I/R
26. gravar alfabeto pelo site (`/gestos/alfabeto/`, Espaço salva), painel do
    alfabeto em Gestos, treino do alfabeto pelo site, recarga automática do
    modelo na câmera, `salvar_modelo_atomico`; 220 testes (o hash do CSV e dos
    modelos reais é conferido antes/depois da suíte)
27. todas as amostras do alfabeto apagadas para regravar; modelo atual (19
    letras) registrado

---

## 7. Pendências e próximos passos

1. ~~Gravar o Z pelo site~~ — feito (20 amostras, ~25 fps).
2. **Treinar com J + Z** (botão do site) e testar a confusão entre eles ao vivo
   (J não pode virar Z e vice-versa); pedir ao usuário as linhas do terminal do
   runserver.
3. **Merge do `melhorias-movimento` no `main`** (ou PR) — quando o usuário
   aprovar.
4. **Exemplos negativos:** gravar "J incompleto" / "I parado" (mecanismo pronto,
   nenhum gravado) — é o que resolve o J pela metade ainda aceito.
5. **Mais pessoas** gravando cada sinal (hoje os dados são de uma pessoa).
6. **Alfabeto estático** (resolve-se com a regravação pelo site, que usa o
   detector do reconhecimento ao vivo): o dataset antigo foi coletado na
   resolução padrão da webcam (desconhecida); a coleta agora é 960×540. O
   `coletar_alfabeto` ainda usa `model_complexity` padrão (1) e confiança
   0.7/0.7, enquanto o reconhecedor usa complexity 0 e 0.65/0.6 — não alinhado
   de propósito (exigiria recoletar). H, K e X não estão no dataset.
7. **Melhoria possível:** com duas abas de câmera abertas, cada uma fica com
   metade do FPS (cada stream roda seu próprio loop). Uma thread única de
   captura compartilhada resolveria.
8. **Front — validar com o usuário** (e, idealmente, com pessoas surdas): a home
   nova, a leitura no celular real e se o português está simples o bastante.
   Ideia sugerida, não implementada (decisão do usuário, depende de internet
   e de script externo): widget VLibras (gov.br), que traduz o texto da página
   para Libras com um avatar.
9. **Notas de prints:** o script de prints usa Chrome `--headless=new`
    (largura mínima ~500 px; para celular usar Edge `--headless=old`). Nunca
    tirar print de `/reconhecer/` ou `/gestos/<id>/gravar/` (abrem a webcam):
    para ver o reconhecer, renderizar o template pelo Django Client, trocar
    `src="/video/"` por uma imagem e sobrescrever `window.fetch` com um
    status roteirizado (foi assim em 2026-10-06).
11. **Página de gravação** (`gravar.html`) ainda tem o visual antigo — pode
    ganhar a mesma linguagem do reconhecer se o usuário quiser.
10. **Plano de auto-aperfeiçoamento** (discutido em 2026-10-06; nada
   implementado; ordem recomendada — o usuário ainda não escolheu por onde
   começar):
   - **Fase 1 — medir:** conjunto de teste fixo (amostras que nunca entram no
     treino, de preferência de outras pessoas) + comando `avaliar_modelos`
     (acerto por sinal, falsos positivos, confusões J×Z). Pré-requisito do
     resto.
   - **Fase 2 — mais dados manuais:** Z, exemplos negativos, outras pessoas.
   - **Fase 3 — coleta pelo uso com confirmação humana:** botões
     "Certo / Errado / Era o sinal X" no `/reconhecer/`; priorizar perguntar
     nos casos de dúvida (distância perto do limiar).
   - **Fase 4 — retreino automático com trava:** `retreinar_auto` só promove o
     modelo novo se não piorar no teste fixo; versões antigas em
     `dados/modelos_treinados/historico/`.
   - **Fase 5 — trocar o modelo de movimento** (DTW compara com todas as
     amostras; com centenas por sinal, migrar para um classificador de
     sequências).
   - Evitar auto-treino só com as próprias previsões, sem confirmação humana:
     o modelo aprenderia com os próprios erros.

---

## 8. Comandos úteis

```powershell
.\.venv\Scripts\python.exe manage.py runserver
.\.venv\Scripts\python.exe manage.py gravar_movimento Z      # sinal precisa existir (tipo Movimento)
.\.venv\Scripts\python.exe manage.py verificar_movimentos     # integridade + fps das amostras
.\.venv\Scripts\python.exe manage.py treinar_movimentos
.\.venv\Scripts\python.exe manage.py testar_movimento --amostra <id>
.\.venv\Scripts\python.exe manage.py testar_movimento --arquivo dados/sinteticos/nao_j_sintetico.json
.\.venv\Scripts\python.exe manage.py test libras
.\.venv\Scripts\python.exe manage.py coletar_alfabeto A       # alfabeto estático (S salva, Q sai)
.\.venv\Scripts\python.exe manage.py treinar_alfabeto
```

**Conferir dados** (sinais, amostras por origem e modelo de movimentos):

```bash
.venv/Scripts/python.exe -c "
import os,django;os.environ['DJANGO_SETTINGS_MODULE']='config.settings';django.setup()
from libras.models import Sinal
from libras.movimento.amostras import ler_sequencia
from libras.movimento import classificador
for s in Sinal.objects.all().order_by('pk'):
    ams=list(s.amostras.filter(ativo=True)); orig={}
    for a in ams:
        o=ler_sequencia(a).get('origem','navegador(antiga)'); orig[o]=orig.get(o,0)+1
    print(s.pk, s.titulo, s.tipo, 'negativo' if s.negativo else '', len(ams), orig)
m=classificador.carregar_modelo()
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
- `libras/captura/camera.py` cria `camera = Camera()` na importação (carrega o
  MediaPipe e o modelo do alfabeto). Os imports de `libras.movimento` ficam
  dentro dos métodos para o módulo carregar leve.
- Cuidado com nomes: o módulo `libras.movimento.trajetoria` colide com
  variáveis locais chamadas `trajetoria` (já causou erro na reorganização);
  use `passos` para a variável.
- `dados/banco.sqlite3` e `dados/amostras_movimento/` estão no `.gitignore`
  (o banco e as gravações não vão para o GitHub); `dados/modelos_treinados/`,
  `dados/amostras_estaticas/` e `dados/sinteticos/` são versionados. `backups/`
  também é ignorada.
- Privacidade: nenhum vídeo é armazenado, só landmarks. Se pessoas de fora forem
  gravar, lembrar o usuário de combinar consentimento.
