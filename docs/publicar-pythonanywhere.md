# Publicar o LibrAI no PythonAnywhere (plano grátis)

Guia passo a passo para colocar o site no ar em
`https://SEU_USUARIO.pythonanywhere.com`, para a equipe gravar e treinar de
casa. Onde aparecer **`SEU_USUARIO`**, troque pelo nome de usuário da conta.

> **O que fica onde.** O código vem do GitHub. Os **dados** (banco, contas,
> amostras e modelos) nascem e ficam **no servidor**, e não vão para o Git.
> Faça backups (passo 9).

## Limites do plano grátis (conferidos em 2026-10-07)

| Limite | Valor | O que significa para nós |
|---|---|---|
| Disco | 512 MiB | Cabe, desde que se aproveitem as bibliotecas já instaladas lá (passo 3). |
| Site | 1 site, 1 processo | Bom para a equipe de 3 pessoas; não é para muito público ao mesmo tempo. |
| Validade | **1 mês** | Todo mês, clique em **"Run until 1 month from today"** na aba **Web**. O PythonAnywhere avisa por e-mail antes. |
| Endereço | `SEU_USUARIO.pythonanywhere.com`, já com https | O https é obrigatório: sem ele o navegador não libera a câmera. |

A câmera e o detector de mão rodam no navegador de cada pessoa, e o servidor
só recebe os pontos da mão. Por isso o plano grátis aguenta.

---

## 1. Criar a conta

1. Acesse https://www.pythonanywhere.com e crie uma conta **Beginner (free)**.
2. O nome de usuário vira o endereço do site. Escolha com cuidado (ex.: `librai`).

## 2. Baixar o código

No painel, abra **Consoles → Bash** e rode:

```bash
git clone https://github.com/VqtorZ/LibrAI.git
cd LibrAI
git checkout melhorias-movimento   # enquanto o trabalho não estiver no main
```

## 3. Ambiente Python (sem estourar o disco)

```bash
mkvirtualenv --python=python3.11 --system-site-packages librai
pip install -r requirements.txt
du -sh ~/.virtualenvs/librai        # tamanho do ambiente; deve ficar pequeno
```

O `--system-site-packages` reaproveita numpy, pandas e scikit-learn, que o
PythonAnywhere já tem instalados. Assim, o `pip` só baixa o que faltar
(normalmente, só o Django). Se o comando `du` mostrar mais de ~300 MB, pare e
avise.

## 4. Configurações secretas (`.env`)

Ainda no Bash, dentro de `~/LibrAI`, gere uma chave secreta:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Crie o arquivo `.env` (pela aba **Files**, ou com `nano .env`) com:

```
LIBRAI_PRODUCAO=1
LIBRAI_SECRET_KEY=COLE_AQUI_A_CHAVE_GERADA
LIBRAI_HOSTS=SEU_USUARIO.pythonanywhere.com
```

- Esse arquivo **nunca** vai para o GitHub (está no `.gitignore`) e **não deve
  ser enviado a ninguém**.
- Sem ele, ou com a chave curta, o site se recusa a subir. Isso é de
  propósito.

## 5. Banco, arquivos estáticos e contas

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy          # deve terminar sem avisos
python manage.py criar_admin victorba.rezende@gmail.com --nome Victor --master
python manage.py criar_admin yasmin.yas@gmail.com --nome Yasmin
python manage.py criar_admin giovana.gii@gmail.com --nome Giovana
```

O `criar_admin` pede a senha na hora; ela não aparece na tela.
- **Senhas novas:** pelo menos 10 caracteres, e nada óbvio (como `12345678910`
  ou `password123`), senão o comando recusa.
- **Não reaproveite as senhas** que foram mandadas no chat.
- O ideal é cada pessoa digitar a própria senha, ou trocar a provisória
  depois (a conta master troca senhas em `/admin/`).

## 6. Criar o site (aba **Web**)

1. **Add a new web app** → **Next** → escolha **Manual configuration**
   (**não** a opção "Django") → **Python 3.11**.
2. Em **Virtualenv**, informe: `/home/SEU_USUARIO/.virtualenvs/librai`
3. Em **Code → Source code**: `/home/SEU_USUARIO/LibrAI`
4. Clique no link do **WSGI configuration file**, apague tudo e cole:

   ```python
   import os
   import sys

   caminho = "/home/SEU_USUARIO/LibrAI"
   if caminho not in sys.path:
       sys.path.insert(0, caminho)
   os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```

   (As configurações secretas vêm do `.env`; não coloque a chave aqui.)
5. Em **Static files**, adicione: URL `/static/` → Directory
   `/home/SEU_USUARIO/LibrAI/staticfiles`
6. Em **Security**, ligue **Force HTTPS**.
7. Clique no botão verde **Reload**.

## 7. Testar

1. Abra `https://SEU_USUARIO.pythonanywhere.com/reconhecer/` e permita a
   câmera. Os pontos devem aparecer na mão.
2. Entre em `/entrar/` com a conta master e confira se a área de Gestos abre.
3. Grave **uma** amostra de teste (por exemplo, uma letra em Gravar letras) e
   confira se a contagem sobe.

Se algo der errado, a aba **Web** tem o **Error log** (erros) e o **Server
log**. Os registros de cada movimento reconhecido também ficam no Server log.

| Sintoma | Causa provável |
|---|---|
| "Bad Request (400)" | `LIBRAI_HOSTS` no `.env` diferente do endereço do site. Corrija e clique em Reload. |
| "403 CSRF" ao salvar/entrar | Acesso por `http://`: ligue Force HTTPS (passo 6.6). |
| "Something went wrong" | Veja o Error log. Normalmente é o caminho errado no WSGI ou no virtualenv. |
| Página sem estilo (sem CSS) | Faltou o `collectstatic` ou o mapeamento de `/static/` (passo 6.5). |
| Câmera não liga | O navegador bloqueou a permissão (ícone ao lado do endereço) ou o site está em http. |
| "Muitas tentativas erradas" no login | 5 senhas erradas no mesmo e-mail: espere 15 minutos. |

## 8. Atualizar o site quando houver código novo

```bash
cd ~/LibrAI
workon librai
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

Depois, clique em **Reload** na aba **Web**. Os dados não são afetados.

## 9. Backup dos dados (faça toda semana e antes de cada atualização)

```bash
cd ~/LibrAI && workon librai
python manage.py backup_dados
```

O comando gera `backups/librai-AAAA-MM-DD-HHMM.zip` com o banco (contas,
sinais), as amostras e os modelos. Baixe o arquivo pela aba **Files** e
guarde fora do servidor. Para restaurar, descompacte o `.zip` dentro de
`~/LibrAI` (com o site parado) e clique em **Reload**. Apague backups antigos
do servidor para não encher os 512 MiB.

## 10. Rotina mensal

- Na aba **Web**, clique em **"Run until 1 month from today"** (senão o site
  sai do ar).
- Faça um backup (passo 9).
