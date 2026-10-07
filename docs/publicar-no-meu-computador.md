# Colocar o LibrAI no ar a partir do seu computador

O site roda no seu PC e um **túnel da Cloudflare** cria um link público com
https (obrigatório para a câmera) apontando para ele. É grátis e não precisa
de conta nem de mexer no roteador.

## Ligar

1. Dê **dois cliques no atalho "LibrAI - colocar no ar"** na Área de Trabalho
   (ou em `publicar.cmd`, na pasta do projeto). Se o site já estiver no ar, a
   janela avisa e mostra o link atual, sem abrir um segundo.
2. Em uns 10 segundos aparece:

   ```
   ================================================================
     LibrAI NO AR:  https://palavras-aleatorias.trycloudflare.com
     Gravar/treinar (equipe):  https://palavras-aleatorias.trycloudflare.com/entrar/
   ================================================================
   ```

3. Mande o link para a equipe (WhatsApp etc.). O link também fica gravado em
   `dados/link_publico.txt`.

**Deixe a janela aberta.** Fechar a janela (ou Ctrl+C) tira o site do ar.

## Importante

- **O link muda toda vez que você liga o site.** Mande o novo para a equipe
  sempre que religar.
- **O computador não pode dormir** enquanto a equipe usa. Em *Configurações →
  Sistema → Energia*, coloque "Suspender" em **Nunca** quando estiver ligado na
  tomada (ou só durante as sessões de gravação).
- **Não precisa rodar o `runserver` junto.** O `publicar.cmd` usa a porta
  8080 e o `runserver` a 8000, então os dois podem rodar juntos sem conflito.
  É o **mesmo banco e as mesmas amostras**.
- Para a equipe, o caminho é: **link → Entrar → Gestos** → *Gravar letras* ou
  a página do sinal → *Gravar nova amostra* → **Treinar**.
- O público em geral usa só a home e o **Reconhecer** (sem conta).

## Segurança

- O servidor escuta **só dentro do seu computador** (127.0.0.1). De fora,
  chega apenas o que passa pelo túnel, ou seja, o site. Nenhuma outra pasta
  ou programa fica exposto.
- O modo "site no ar" usa o arquivo `.env.publico` (chave secreta; **fora do
  Git, nunca envie a ninguém**). Ele desliga o modo de desenvolvimento,
  obriga https nos cookies e bloqueia o login por 15 min depois de 5 senhas
  erradas.
- **Troque as senhas das contas antes de mandar o link.** As senhas antigas
  passaram pelo chat. Em um terminal, na pasta do projeto, rode:

  ```powershell
  .\.venv\Scripts\python.exe manage.py criar_admin victorba.rezende@gmail.com --nome Victor --master
  .\.venv\Scripts\python.exe manage.py criar_admin yasmin.yas@gmail.com --nome Yasmin
  .\.venv\Scripts\python.exe manage.py criar_admin giovana.gii@gmail.com --nome Giovana
  ```

  (10+ caracteres, nada óbvio.) Depois, **cada pessoa troca a própria
  senha** pelo site: clicar em **"Olá, Nome"** no topo (ou no menu do
  celular, "Trocar minha senha") → `/conta/senha/`. Assim você só precisa
  passar uma senha provisória, e cada uma define a sua.
- Nenhum vídeo sai do aparelho de quem usa: só os pontos da mão.

## Backup

Os dados ficam no seu PC, em `dados/`. Faça uma cópia toda semana:

```powershell
.\.venv\Scripts\python.exe manage.py backup_dados
```

Guarde o `.zip` de `backups/` em outro lugar (Google Drive, pendrive).

## Limites desta solução

- Os links `trycloudflare.com` são o modo "rápido" da Cloudflare, feito para
  testes. Funcionam bem para a equipe, mas sem garantia de ficarem no ar
  sempre.
- **Link fixo**, se um dia fizer falta: um domínio próprio na Cloudflare
  (túnel nomeado), ngrok com domínio grátis ou Tailscale Funnel. Todos pedem
  uma conta; o restante do projeto não muda.
- O desempenho depende do seu PC e da sua internet de upload. Para 3 pessoas
  gravando, sobra.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Janela fecha com "cloudflared não encontrado" | `winget install --id Cloudflare.cloudflared -e` |
| "O túnel não respondeu" | Confira a internet e rode o `publicar.cmd` de novo. |
| Link abre "Bad gateway" / 502 | A janela foi fechada ou o PC dormiu: religue e mande o link novo. |
| Câmera não liga | Permita a câmera no navegador (ícone ao lado do endereço). |
| "Muitas tentativas erradas" | 5 senhas erradas no mesmo e-mail: espere 15 minutos. |
