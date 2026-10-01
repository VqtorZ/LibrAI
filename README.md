# LIBRAS Vision

Aplicação local em Django que transmite a webcam via OpenCV e reconhece alguns
gestos estáticos demonstrativos de Libras (`A`, `B`, `L` e `S`) usando marcos da
mão do MediaPipe.

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
é aberta pelo processo Python, portanto permita o acesso à câmera nas
Configurações de Privacidade do Windows e feche aplicativos que já a estejam usando.

## Treinar o alfabeto

O reconhecimento de todas as letras estáticas usa um classificador treinado com
os 21 marcos da mão. Instale as novas dependências e colete amostras:

```powershell
pip install -r requirements.txt
python scripts/coletar_libras.py
```

Escolha uma letra, faça o sinal diante da câmera e pressione `S` para salvar
cada amostra. Repita para `A` até `Z`, variando pessoas, mãos, iluminação e
distância. Depois treine:

```powershell
python scripts/treinar_libras.py
python manage.py runserver
```

O modelo será salvo em `models/libras_alphabet.joblib` e carregado
automaticamente pela câmera. Sem esse arquivo, a interface informa que o modelo
ainda não foi treinado. `J` e `Z` são sinais com movimento e precisam de um
modelo temporal específico; o classificador estático não pode reconhecê-los
corretamente a partir de um único frame.

## Limites e evolução

O mapeamento atual é intencionalmente pequeno e serve para validar toda a
integração (landing page → Django → OpenCV → webcam → interface). Libras inclui
movimento, orientação e contexto; para um tradutor real, colete um conjunto de
vídeos/imagens rotulados e troque `Camera.classify` em `libras/vision.py` por um
modelo treinado, por exemplo TensorFlow ou scikit-learn sobre sequências dos 21
marcos de mão.
