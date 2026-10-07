"""Sinais com movimento (J, Z, gestos): da gravação ao reconhecimento.

A câmera é a do navegador: lá o MediaPipe acha os pontos da mão e só os
números chegam ao servidor. Fluxo de uma amostra:

1. ``amostras`` — valida os quadros recebidos e salva/lê o JSON da amostra;
2. (a página de gravação manda os quadros para ``views.gesto_amostra_gravar``)
3. ``verificacao`` — confere se os arquivos estão íntegros;
4. ``segmentacao`` — recorta o trecho em que a mão se moveu;
5. ``trajetoria`` — transforma os frames em números comparáveis;
6. ``classificador`` — DTW: treino, limiar de rejeição e previsão;
7. ``ao_vivo`` / ``sessoes`` — reconhecimento ao vivo, uma sessão por aba.
"""
