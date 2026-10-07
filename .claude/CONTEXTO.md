# LibrAI — memória do projeto

Arquivo de contexto para retomar o trabalho (palavra-chave **RELEMBRE**).
Última atualização: **2026-10-07**.

---

## 1. Estado atual (onde paramos)

- **Branch de trabalho:** `melhorias-movimento` (enviado ao GitHub,
  `origin/melhorias-movimento`). Tem 34+ commits que ainda não estão no `main`
  (o `main` está em `e61c9d3`). O merge (ou PR) espera a aprovação do
  usuário: https://github.com/VqtorZ/LibrAI/pull/new/melhorias-movimento
- **Testes:** 262 passando (`libras/tests/`, divididos por área).
- **Objetivo em andamento (2026-10-07): colocar o site no ar** para a equipe
  de três pessoas (Victor, Yasmin, Giovana) gravar amostras e treinar a IA
  remotamente. Decisões do usuário: **câmera migrada para o navegador**
  (recomendação aceita) e hospedagem no **PythonAnywhere (grátis)**.
  - **Etapas 1 a 3 FEITAS** (commit "feat: câmera no navegador…"): formato
    de dados v3, servidor sem câmera (o navegador manda só os pontos) e
    câmera do navegador nas três páginas (Reconhecer, Gravar letras, Gravar
    movimento). Teste de fumaça com Chrome headless e câmera falsa: MediaPipe
    carregou do CDN (WebGL), vídeo 960×540, 51 lotes `POST /api/quadros/` com
    200 em ~15 s, "Sem mão" correto. **Não testado com mão real**: o usuário
    precisa testar ao vivo.
  - **Etapa 4 FEITA** (código): modo produção por `.env` (`config/ambiente.py`;
    `LIBRAI_PRODUCAO`, `LIBRAI_SECRET_KEY`, `LIBRAI_HOSTS`; sem `.env` = modo
    local de sempre), cookies seguros/HSTS, `STATIC_ROOT=staticfiles/`,
    `check --deploy` limpo, login bloqueado 15 min após 5 erros no e-mail ou
    20 no IP (`X-Real-IP` em produção), senhas novas com 10+ caracteres
    (`criar_admin` valida), comando `backup_dados` (.zip) e o guia
    **`docs/publicar-pythonanywhere.md`**. Plano grátis conferido em
    2026-10-07: 512 MiB de disco, 1 site/1 processo, **expira a cada 1 mês**
    (renovar na aba Web).
  - **Falta (com o usuário):** criar a conta no PythonAnywhere e seguir o guia;
    testar ao vivo.
- **Dados após a migração (conferido em 2026-10-07):**
  - Banco: `#2 J` com 26 amostras e `#3 Z` com 20, **todas versão 2** (câmera
    do servidor). Ficam guardadas, mas fora dos treinos; a situação dos dois
    sinais aparece como **"Regravar"**. **J e Z precisam ser regravados pelo
    site.**
  - `dados/modelos_treinados/` está **vazia**: os modelos antigos foram
    movidos para `dados/legado/` (`movimentos_camera_servidor.joblib` = J+Z;
    `alfabeto_camera_servidor.joblib` = modelo A–E).
  - `dados/amostras_estaticas/` está **vazia**: as 810 amostras A–E gravadas
    pelo caminho antigo foram para `dados/legado/alfabeto_camera_servidor.csv`.
    As novas vão para `dados/amostras_estaticas/alfabeto.csv`. **O alfabeto
    recomeça do zero.**
  - O usuário foi orientado a **não gravar** até a migração terminar.
- **Login (2026-10-07):** `/entrar/` (e-mail + senha). Livres: home,
  Reconhecer e `POST /api/quadros/`. Só administradores (`is_staff`,
  decorador `acesso.apenas_admin`): toda a área de Gestos. Contas no banco local
  (senhas só no banco, criptografadas; **nunca escrever senhas em arquivos do
  projeto**):
  - `victorba.rezende@gmail.com` (master, `is_superuser`, nome Victor);
  - `yasmin.yas@gmail.com` (Yasmin);
  - `giovana.gii@gmail.com` (Giovana; o usuário digitou "giovana,gii" e o
    endereço foi corrigido para ponto, falta confirmar com ele).

  Recomendamos ao usuário trocar as senhas: elas foram enviadas no chat, e as
  de Yasmin e Giovana são fracas. Novas contas: `manage.py criar_admin`. No
  servidor de produção, as contas terão de ser criadas de novo, porque o banco
  local não sobe.
- **Kanban no Trello (2026-10-07):** quadro **LibrAI** em
  https://trello.com/b/nTSkTuue/librai (área de trabalho de VqtorZ).
  - Colunas: Ideias → A fazer → Fazendo → Para validar → Feito.
  - Etiquetas: Alfabeto, Movimento, Site, IA/Dados, Segurança, Infra.
  - 28 cartões criados a partir das pendências desta memória.
  - Acesso pela API do Trello: credenciais em `C:/Users/victo/.trello-librai.json`
    (fora do projeto; **nunca imprimir, repetir no chat ou copiar para o
    projeto**); ids do quadro, listas e etiquetas em
    `C:/Users/victo/.trello-librai-quadro.json`.
  - O token vale 30 dias (até ~2026-11-06); depois, gerar outro pelo link de
    autorização com a chave do app "LibrAI Kanban".
  - Ao concluir tarefas, oferecer mover os cartões.
- **Próximo passo:** o usuário testa ao vivo localmente, cria a conta no
  PythonAnywhere e segue o guia (posso acompanhar passo a passo); cria as
  contas lá com senhas novas; a equipe regrava o alfabeto, o J e o Z.
- **Mudança no Git (2026-10-07):** `dados/amostras_estaticas/` e
  `dados/modelos_treinados/` passaram para o `.gitignore` (os dados nascem no
  servidor; versioná-los faria o `git pull` de lá brigar com eles).

---

## 2. O projeto

Aplicação **Django** que reconhece Libras pela webcam usando os 21 marcos
(landmarks) da mão do MediaPipe. **Desde 2026-10-07, a câmera é a do
navegador:** o MediaPipe Tasks Vision (JS, 0.10.21, via CDN jsdelivr; o modelo
`hand_landmarker.task` fica em `static/modelos/`) roda na página, e só os
pontos vão para o servidor. Dois pipelines:

- **Estático (alfabeto manual):** um RandomForest classifica a letra a partir
  das 63 coordenadas normalizadas + 10 distâncias entre as pontas dos dedos.
  Gravação pelo site (Gestos → Gravar letras, Espaço salva). Treino pelo
  botão do site ou com `manage.py treinar_alfabeto`.
- **Movimento (J, Z, gestos):** amostras temporais (sequências de landmarks)
  comparadas por DTW (vizinho mais próximo) com limiar de rejeição.

Ambiente: Windows 11, Python 3.11.9 em `.venv`, Django 5.2, scikit-learn 1.9.
O `requirements.txt` não tem mais OpenCV nem mediapipe (o servidor não usa
câmera). Remoto: https://github.com/VqtorZ/LibrAI.git

Rodar: `.\.venv\Scripts\python.exe manage.py runserver` → http://127.0.0.1:8000/
(o terminal precisa ficar aberto; "ERR_CONNECTION_REFUSED" = servidor parado).
O navegador só libera a câmera em `localhost` ou `https`.

---

## 3. Arquitetura (pastas e responsabilidades)

O README tem o mapa completo em árvore. Resumo:

**Dados — `dados/`** (caminhos definidos só em `libras/caminhos.py`, que também
é usado pelo `config/settings.py`):

| Caminho | Conteúdo | Git |
|---|---|---|
| `dados/banco.sqlite3` | banco do Django (sinais + registro das amostras) | não |
| `dados/amostras_estaticas/alfabeto.csv` | alfabeto: letra + 63 coordenadas por linha (formato v3) | sim |
| `dados/amostras_movimento/<id>-<slug do título>/<amostra>.json` | uma amostra de movimento por arquivo (MEDIA_ROOT); o caminho de cada uma fica salvo no banco (`AmostraMovimento.arquivo_dados`) | não |
| `dados/modelos_treinados/` | `alfabeto.joblib` (dict `{formato: 3, treinado_em, modelo}`), `movimentos.joblib` (formato 3) | sim |
| `dados/legado/` | CSV e modelos do tempo da câmera do servidor (nunca entram nos treinos) | sim |
| `dados/sinteticos/nao_j_sintetico.json` | dado artificial do teste de rejeição | sim |

**Formato v3 dos pontos** (`static/js/camera-maos.js`):
- espelhados como numa selfie: `x' = (1 - x) * proporção`, `y' = y`,
  `z' = z * proporção`, com proporção = largura / altura da imagem;
- a mão "Left"/"Right" vem trocada, porque o MediaPipe vê a imagem sem
  espelhar.

Assim, o mesmo gesto dá os mesmos números em webcams 16:9 e 4:3. As versões
ficam registradas assim:
- `amostras.FORMATO_VERSAO = 3`, gravado no JSON e em
  `AmostraMovimento.versao_features`;
- `classificador.FORMATO_MODELO = 3`;
- `estatico.classificador.FORMATO_ALFABETO = 3`.

Amostras e modelos de versões antigas ficam fora dos treinos ou são
recusados.

**Código — `libras/`:**

| Arquivo | Papel |
|---|---|
| `caminhos.py` | Fonte única dos caminhos de dados (sem Django) e `salvar_modelo_atomico` (`.tmp` + `os.replace`). |
| `estatico/features.py` | `extrair_features`, `extrair_features_de_valores` (63 coords relativas ao pulso + 10 distâncias) e `features_geometricas`. |
| `estatico/amostras.py` | CSV do alfabeto: `salvar`, `contar`, `desfazer` (só a última linha), `validar_letra`, `CABECALHO`, `LETRAS_ESTATICAS` (A–Z sem J e Z). Caminho lido na hora da chamada (testes redirecionam `AMOSTRAS_ESTATICAS`). |
| `estatico/treino.py` | `treinar(dataset, destino)` do RandomForest (`random_state=42`); salva o dict do formato 3. |
| `estatico/classificador.py` | `ClassificadorAlfabeto` (singleton `alfabeto`): recarrega o modelo quando o arquivo muda (confere no máximo a cada 2 s), recusa formato antigo, `pronto`, `letras` (property), `classificar(marcos)` (limiar 0,70; `SEM_MODELO` / `NAO_IDENTIFICADO`). |
| `movimento/amostras.py` | Validação do que vem do navegador: `validar_marcos`, `validar_quadros` (tipos, limites, ordem; `{"t","marcos","mao"}` → `{"timestamp_ms","landmarks","mao"}`), `sequencia_de_gravacao` (tempo a partir de 0, máximo 30 s / 1200 quadros). Persistência: `salvar_amostra(..., origem="navegador")`, `ler_sequencia`, `apagar_amostra`, `apagar_sinal`, `pasta_do_sinal`. |
| `movimento/verificacao.py` | Verificador estrutural dos JSONs: `verificar_conteudo` (sem banco) e `verificar_amostra` (confere com o banco). |
| `movimento/segmentacao.py` | `Segmentador` (início/fim do movimento por velocidade), `recortar`, `segmentos`, `trecho_principal`. |
| `movimento/trajetoria.py` | `normalizar_frame`, `processar_frames` (forma + deslocamento do pulso, espelhamento, reamostragem, aparo de repouso). |
| `movimento/classificador.py` | `distancia_dtw`, `treinar` (só amostras v3), `_calibrar`/limiares, `carregar_modelo`, `prever`, `remover_do_modelo`, `situacao_dos_sinais` (códigos `regravar`, `sem_amostras`, `poucas`, `pronto`, `treinar`), `MODELO_PATH`. |
| `movimento/ao_vivo.py` | `DetectorMovimento`: quadros → segmentação → previsão quando a mão para; recarrega o modelo quando o arquivo muda; log `libras.movimento.ao_vivo`. |
| `movimento/sessoes.py` | Uma `SessaoAoVivo` por aba (canal UUID aleatório): detector de movimento próprio, rótulo da tela (movimento > "Analisando movimento…" > letra parada do último quadro > "Aguardando mão"), movimento exibido por 2,5 s no relógio do navegador. Máximo 200 sessões; ociosas somem após 600 s. |
| `models.py` | `Sinal` (titulo, tipo ESTATICO/MOVIMENTO, **negativo**, descricao, ativo) e `AmostraMovimento` (metadados + caminho do JSON + `versao_features`). Migrações até `0003_sinal_negativo`. |
| `views.py` / `urls.py` | `inicio`, `reconhecer`, `api_quadros` (público, lotes de até 90 quadros), `gestos`, `gesto_*`, `gesto_amostra_gravar` (JSON `{quadros}`), `alfabeto_*` (salvar com JSON `{letra, marcos}`), `entrar`/`sair`. Helper `_json(request)`. |
| `acesso.py` | Login: `FormularioEntrar` (e-mail em minúsculas, mensagens em PT, recusa conta sem `is_staff`) e o decorador `apenas_admin`. |
| `contexto.py` | Context processor `versao_estaticos`: CSS e JS levam `?v=<mtime>` (inclui `js/camera-maos.js`). |
| `management/commands/` | `treinar_alfabeto`, `verificar_movimentos`, `treinar_movimentos`, `testar_movimento`, `gerar_nao_j_sintetico`, `criar_admin`. (`coletar_alfabeto` e `gravar_movimento` foram removidos com a câmera do servidor.) |
| `tests/` | `base.py` + `test_sinais`, `test_amostras`, `test_classificador`, `test_ao_vivo` (detector, sessões, API), `test_gravacao` (gravação pelo navegador), `test_alfabeto`, `test_alfabeto_site`, `test_acesso`, `test_exclusao`, `test_paginas`. |
| `templates/libras/` | `_camera_navegador.html` (vídeo + canvas dos pontos + aviso de permissão/erro + "Tentar de novo" + nota de privacidade), `reconhecer`, `alfabeto_gravar`, `gravar` (visual `rc-*`, lista "Salvas nesta visita"), `gesto_detalhe` (aviso de amostras antigas), `inicio`, `gestos`, `_cabecalho`, `_botao_treinar`, `_confirmar_exclusao`. |
| `static/js/camera-maos.js` | Módulo ES: `ligarCameraMaos` (GPU com fallback para CPU, 960×540, desenha os pontos espelhados), `criarEnvioAoVivo` (lotes a cada 250 ms, fila de no máximo 80), `enviarJson`, `iniciarCameraDaPagina`. |
| `static/css/` | `app.css` (geral; `.situacao--regravar`, `.nota-antigas`), `home.css`, `reconhecer.css` (classes `rc-*`, também usadas nas páginas de gravação). Regra global `[hidden] { display: none !important }`. |
| `config/settings.py` | `LOGGING` mostra o logger `libras` (INFO). Ainda **sem** configurações de produção (etapa 4). |

**Rotas:**
- públicas: `/`, `/reconhecer/`, `POST /api/quadros/`, `/entrar/`,
  `POST /sair/`;
- Gestos:
  - lista e treino: `/gestos/`, `/gestos/novo/`, `POST /gestos/treinar/`;
  - alfabeto: `/gestos/alfabeto/`, `POST /gestos/alfabeto/amostras/`,
    `POST /gestos/alfabeto/desfazer/`, `POST /gestos/alfabeto/treinar/`;
  - sinal: `/gestos/<id>/`, `/gestos/<id>/gravar/`,
    `POST /gestos/<id>/amostras/` (salva uma gravação), `/gestos/<id>/excluir/`
    (GET confirma, POST exclui),
    `POST /gestos/<id>/amostras/<amostra_id>/apagar/`.

A resposta de `/api/quadros/` traz `label`, `movement_label`,
`hand_detected`, `model_ready` e `movement_ready`.

---

## 4. Pipeline de movimento (como funciona hoje)

1. **Captura** (câmera do navegador, o mesmo detector do reconhecimento):
   - página `/gestos/<id>/gravar/`: mostra a câmera com os 21 pontos e o
     indicador "Mão detectada". **Espaço** inicia e para; os quadros vão de uma
     vez para `POST /gestos/<id>/amostras/`. Para sozinho aos 30 s ou 1200
     quadros.
   - Protocolo de gravação:
     1. configuração inicial com a mão **parada** (no J, o I);
     2. Espaço;
     3. movimento completo;
     4. mão parada;
     5. Espaço.
2. **Segmentação** (`movimento/segmentacao.py`, usada no treino **e** ao vivo):
   - velocidade = norma da variação de [forma normalizada + pulso/tamanho da
     mão] por segundo, média de 3 frames;
   - o movimento começa com ≥ 6.0 u/s e termina após 350 ms abaixo de 4.0 u/s
     (ou sem mão, ou aos 4 s);
   - mínimo de 400 ms de movimento, com 300 ms de contexto antes;
   - nas gravações, `trecho_principal` usa o movimento mais longo.

   Os limiares foram calibrados com dados da câmera antiga; **revalidar com
   amostras v3**.
3. **Features por passo** (`movimento/trajetoria.py`, 65 valores):
   - 63 da forma da mão (relativa ao pulso e à escala);
   - 2 do **deslocamento do pulso** desde o início, em tamanhos de mão;
   - antes: lacunas interpoladas, mão esquerda espelhada e reamostragem a
     66 ms;
   - depois: aparo do repouso das pontas.
4. **Classificação** (`prever`): vizinho mais próximo por DTW. Rejeita se a
   distância passar do limiar da classe **ou** se um exemplo negativo estiver
   mais perto.
5. **Limiar** (`_calibrar`): **mediana** das distâncias leave-one-out × 1.5
   (mínimo 0.05), ajustado pelos negativos.
6. **Ao vivo** (`/reconhecer/` → `/api/quadros/` → `sessoes`):
   - enquanto a mão se move, a tela mostra "Analisando movimento…";
   - um movimento aceito aparece por 2,5 s;
   - o log do servidor registra cada movimento.
7. **Exemplos negativos:** sinais marcados como "Exemplo negativo" não viram
   classe; só apertam a rejeição.

---

## 5. Decisões importantes e por quê (com evidências medidas)

- **Câmera no navegador (decisão do usuário, 2026-10-07):** para pôr o site
  no ar com a equipe gravando de casa, a câmera do servidor não serve (na
  nuvem não há câmera, e cada pessoa precisa usar a própria).
  - **Como ficou:** o MediaPipe roda no navegador e o servidor recebe só os
    pontos. A imagem nunca sai do aparelho, o que é bom para a privacidade.
  - **Custo aceito:** os pontos do MediaPipe JS não são idênticos aos do
    Python antigo, então os dados antigos foram arquivados como legado e tudo
    será regravado.
  - **Proteção:** as versões no formato impedem misturar dados antigos e
    novos.
- **Hospedagem: PythonAnywhere grátis (decisão do usuário):** HTTPS em
  `*.pythonanywhere.com`, que a câmera exige, e sem custo.
- **Deslocamento do pulso nas features:** a normalização antiga descartava o
  movimento do braço; o Z ficaria idêntico a uma mão parada apontando.
- **Limiar pela mediana (não pelo máximo):** com 4–5 amostras, um par distante
  estourava o limiar e o modelo aceitava mão parada (mediana×1.5 aceitou 5/5 J
  e rejeitou 100% dos J invertidos, mãos paradas e Z simulados).
- **Mesma segmentação no treino e ao vivo:** o replay foi de 3/5 para **5/5**.
- **Causa do antigo "J reconhecido como I":** gravações com a mão entrando e
  saindo do quadro sem pontos visíveis. Por isso as páginas de gravação
  mostram os pontos, e o protocolo pede a mão parada no início e no fim.
- **Termo de pontas no DTW (testado e descartado).**
- **Sem bases de dados externas, por ora (decisão do usuário, 2026-10-06):**
  apenas sinais brasileiros e gravações próprias. Não voltar a sugerir sem que
  o usuário peça.

---

## 6. Histórico

### Antes de 2026-10-06 (já no `main`)
Projeto inicial (A–D estáticos) → classificador RandomForest do alfabeto →
cadastro de sinais → tipo estático/movimento → coleta temporal → verificador →
DTW experimental → teste de rejeição não-J.

### 2026-10-06 e 2026-10-07 (branch `melhorias-movimento`)
1–13. Movimento:
   - lateralidade;
   - features v2;
   - exemplos negativos;
   - reconhecimento ao vivo;
   - resolução 960×540;
   - `gravar_movimento`;
   - diagnóstico no terminal;
   - gravação pela câmera do servidor;
   - modelo com 26 J;
   - FPS do site.
14–18. Memória `.claude/`, decisão sobre bases externas, reorganização em
   `dados/` + `captura/estatico/movimento/`, nomes em português.
19–24. Front:
   - correção do header;
   - home nova;
   - treino pelo site;
   - Gestos renovado;
   - Reconhecer renovado (câmera maior, sem o selo).
25–28. Modelo J+Z; alfabeto apagado para regravar; modelo do alfabeto apagado.
29. Excluir sinal inteiro com confirmação (232 testes).
30. Login e área de Gestos só para admins (247 testes).
31. `4298b1e` Kanban do Trello registrado na memória.
32. **Câmera no navegador (etapas 1–3 do deploy):**
   - formato v3;
   - `api_quadros` + `sessoes.py`;
   - `estatico/classificador.py`;
   - `camera-maos.js` + `_camera_navegador.html`;
   - Reconhecer, Gravar letras e Gravar movimento no navegador;
   - página de gravação no visual `rc-*`.

   Também foram feitos:
   - remoção de `captura/`, `movimento/gravacao.py`, `coletar_alfabeto` e
     `gravar_movimento`;
   - opencv e mediapipe fora do `requirements.txt`;
   - dados antigos em `dados/legado/`;
   - situação "Regravar" e aviso das amostras antigas;
   - `ClassificadorAlfabeto.letras` virou property (antes ficava vazia até a
     primeira classificação).

   Resultado: 250 testes e teste de fumaça com câmera falsa.
33. Produção: `.env`, segurança, limite de login, validação de senha,
   `backup_dados`, guia do PythonAnywhere; dados fora do Git; 262 testes.
34. Fluidez da câmera (usuário relatou FPS baixo em 2026-10-07). Medido com
   câmera falsa: o laço por requestAnimationFrame rodava o detector 74×/s
   para 20 quadros/s da câmera (~900 ms de trabalho por segundo). Agora:
   - uma detecção por quadro novo (`requestVideoFrameCallback`), ~3× menos
     trabalho;
   - modo adaptativo: em máquina lenta, o detector espera entre análises (no
     máximo ~metade do tempo da página), garantindo ≥ 15/s;
   - animações sobre o vídeo só com transform/opacity e chips sem
     `backdrop-filter`;
   - **modo diagnóstico**: `?diagnostico=1` em qualquer página com câmera
     mostra GPU/CPU, resolução, FPS da câmera e do detector e ms por
     detecção.
35. Medido na máquina do usuário (2026-10-07, `?diagnostico=1`): GPU, câmera
   12 fps, detector 12 fps, **60,6 ms por detecção** — a análise travava a
   página e a câmera. Solução:
   - detector num **Web Worker** (`static/js/detector-maos-worker.js`,
     clássico; o pacote `vision_bundle.cjs` fica em `static/js/vendor/`
     porque o CDN o entrega como `application/node` e o navegador recusa;
     o WASM continua no CDN). O vídeo não espera mais o detector; imagens
     chegam enquanto ele está ocupado são puladas;
   - análise em imagem reduzida a 640 px de largura (`createImageBitmap`,
     mesma proporção, pontos normalizados iguais);
   - **escolha automática GPU × CPU**: começa na GPU; se a média passar de
     25 ms, mede a CPU nas mesmas imagens e fica com a mais rápida (testado
     com `--disable-gpu`: trocou para CPU, ~21 ms);
   - reserva: sem Worker/OffscreenCanvas, roda na página (modo adaptativo).
   **Resultado medido pelo usuário (2026-10-07):** CPU (worker), câmera
   **30 fps**, detector 26 fps, 21,9 ms por detecção — "está ótimo agora".
   Na máquina dele, a CPU foi mais rápida que a GPU (60,6 ms → 21,9 ms).

---

## 7. Pendências e próximos passos

1. **Publicar** seguindo `docs/publicar-pythonanywhere.md` (o usuário cria a
   conta). Ideia futura: página "trocar minha senha" para cada admin.

   Pontos de atenção:
   - o PythonAnywhere grátis tem CPU limitada e **um processo**, e as sessões
     ao vivo ficam em memória, o que funciona com um worker;
   - a gravação de arquivos em `dados/` precisa persistir lá;
   - verificar se o plano grátis libera o CDN jsdelivr: ele é carregado pelo
     navegador, não pelo servidor, então não deve ser problema.
2. **Teste ao vivo pelo usuário** (com mão real) das três páginas novas:
   Reconhecer, Gravar letras e Gravar movimento. Conferir FPS, pontos
   desenhados, "Mão detectada" e se a amostra salva.
3. **Regravar tudo no formato v3:**
   - alfabeto (pela equipe, várias pessoas);
   - J e Z (pelo site);
   - depois treinar;
   - revalidar os limiares da segmentação com dados v3.
4. **Merge do `melhorias-movimento` no `main`**, quando o usuário aprovar.
   Provavelmente antes do deploy, ou publicar direto do branch.
5. **Exemplos negativos:** gravar "J incompleto" / "I parado".
6. **Front:** validar com o usuário e com pessoas surdas. Ideia não
   implementada: widget VLibras.
7. **Plano de auto-aperfeiçoamento** (discutido em 2026-10-06; nada
   implementado):
   1. medir: conjunto de teste fixo + `avaliar_modelos`;
   2. mais dados manuais;
   3. coleta pelo uso com confirmação humana;
   4. retreino automático com trava;
   5. trocar o DTW por um classificador de sequências quando houver centenas
      de amostras.

   Nunca auto-treinar só com as próprias previsões.
8. Trello: atualizar os cartões. Câmera no navegador = feito; deploy =
   fazendo.

---

## 8. Comandos úteis

```powershell
.\.venv\Scripts\python.exe manage.py runserver
.\.venv\Scripts\python.exe manage.py verificar_movimentos     # integridade + fps das amostras
.\.venv\Scripts\python.exe manage.py treinar_movimentos
.\.venv\Scripts\python.exe manage.py treinar_alfabeto
.\.venv\Scripts\python.exe manage.py testar_movimento --amostra <id>
.\.venv\Scripts\python.exe manage.py test libras
.\.venv\Scripts\python.exe manage.py criar_admin email --nome Nome [--master]
```

**Conferir dados** (sinais, amostras por versão do formato, modelos):

```bash
.venv/Scripts/python.exe -c "
import os,django;os.environ['DJANGO_SETTINGS_MODULE']='config.settings';django.setup()
from libras.models import Sinal
for s in Sinal.objects.all().order_by('pk'):
    ams=list(s.amostras.filter(ativo=True)); vers={}
    for a in ams: vers[a.versao_features]=vers.get(a.versao_features,0)+1
    print(s.pk, s.titulo, s.tipo, 'negativo' if s.negativo else '', len(ams), 'por versao:', vers)
" 2>/dev/null; ls dados/modelos_treinados dados/amostras_estaticas
```

---

## 9. Notas para o Claude (ambiente e armadilhas)

- **Heredocs no Bash deste Windows quebram** com crases, `${...}` ou aspas
  dentro de código Python/JS ("unexpected EOF"): escreva scripts de edição num
  arquivo (ferramenta Write, no scratchpad) e execute com o Python da `.venv`.
  Nas edições por script, use `assert texto.count(trecho) == 1`.
- **Teste de fumaça da câmera:** script Node em
  `scratchpad/fumaca.mjs`, que sobe o Chrome headless com
  `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream` e
  controla a página pelo protocolo de depuração (WebSocket nativo do Node 24),
  em tempo real.
  - O `--screenshot` com `--virtual-time-budget` **não serve**: congela no
    pedido da câmera.
  - Subir o servidor de teste na porta 8765 e, no fim, matar **só o PID
    dessa porta**, nunca todos os `python.exe`, porque o usuário pode estar
    com o runserver dele aberto.
- Não abra a webcam real: quem faz o gesto é o usuário. Valide a lógica com
  testes e sessões simuladas.
- Testes: conferir o hash de `dados/` antes e depois da suíte (nenhum teste
  pode tocar nos dados reais).
- Cuidado com nomes: o módulo `libras.movimento.trajetoria` colide com
  variáveis locais chamadas `trajetoria`; use `passos`.
- No `.gitignore`: banco, `amostras_movimento/`, `amostras_estaticas/`,
  `modelos_treinados/`, `staticfiles/`, `.env`. Versionados: `dados/legado/` e
  `dados/sinteticos/`. O `.env` local não deve existir (ligaria a produção). `backups/` é ignorada.
- Privacidade: nenhum vídeo é armazenado, nem sai do navegador; só os
  landmarks. Se pessoas de fora forem gravar, lembrar o usuário de combinar o
  consentimento.
