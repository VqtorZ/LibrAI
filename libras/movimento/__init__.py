"""Sinais com movimento (J, Z, gestos): da gravação ao reconhecimento.

Fluxo de uma amostra:

1. ``gravacao`` — grava a amostra pela câmera (página ou comando);
2. ``amostras`` — salva/lê o JSON da amostra e o registro no banco;
3. ``verificacao`` — confere se os arquivos estão íntegros;
4. ``segmentacao`` — recorta o trecho em que a mão se moveu;
5. ``trajetoria`` — transforma os frames em números comparáveis;
6. ``classificador`` — DTW: treino, limiar de rejeição e previsão;
7. ``ao_vivo`` — aplica tudo isso à câmera do reconhecimento.
"""
