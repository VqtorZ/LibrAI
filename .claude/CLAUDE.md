# LibrAI — instruções para o Claude

Projeto Django local que reconhece Libras pela webcam (OpenCV + MediaPipe):
alfabeto estático (RandomForest) e sinais com movimento (J, Z…) por DTW.
Comunique-se sempre em **português brasileiro**, de forma clara e direta.

## Palavra-chave RELEMBRE

Quando o usuário escrever **RELEMBRE** (em qualquer caixa, sozinho ou na frase),
retome o projeto a partir da memória salva:

1. Leia **inteiro** o arquivo `.claude/CONTEXTO.md` (histórico, arquitetura,
   decisões, estado atual e pendências).
2. Confira se o estado descrito ainda vale: rode `git status -sb`,
   `git log --oneline -5` e, se for falar de dados/modelos, o comando de
   "Conferir dados" da seção *Comandos úteis* do CONTEXTO.md. Se algo mudou
   (commits novos, amostras novas), diga o que mudou.
3. Responda com um resumo curto: o que é o projeto, onde paramos, o que está
   pendente — e pergunte por onde seguir (ou retome a pendência que estava
   combinada com o usuário).

O comando `/relembre` faz o mesmo.

## Manter a memória viva

Ao concluir uma etapa relevante (normalmente junto de um commit), atualize
`.claude/CONTEXTO.md`: seções *Estado atual*, *Histórico* e *Pendências*.
Escreva datas absolutas (ex.: 2026-10-06), fatos verificados e números medidos —
nunca suposições. Commite a atualização junto com o trabalho.

## Convenções de trabalho

- Testes: `.venv/Scripts/python.exe manage.py test libras` (todos devem passar
  antes de cada commit; acrescente testes para mudanças de comportamento).
- Commits em português, no estilo `feat:`/`fix:`/`perf:`/`docs:`/`chore:`,
  terminando com a linha `Co-Authored-By` indicada pelo sistema. O usuário pede
  commits e push frequentes ("para qualquer problema é só voltar").
- Trabalhe no branch indicado em *Estado atual*; merge no `main` só com
  aprovação do usuário.
- O Claude **não consegue testar com a webcam** (hardware do usuário): valide a
  lógica com testes/dados gravados e peça ao usuário o teste ao vivo e a saída
  do terminal do `runserver`.
- Decisões de produto/arquitetura com impacto grande (ex.: mudar o caminho de
  captura, recoletar dados) são do usuário: apresente opções e uma recomendação.
