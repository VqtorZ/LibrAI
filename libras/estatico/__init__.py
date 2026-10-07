"""Alfabeto estático: letras reconhecidas frame a frame (RandomForest).

* ``amostras`` — o CSV das amostras gravadas pelo site;
* ``features`` — como a mão vira números (63 coordenadas + distâncias);
* ``treino`` — treina o classificador a partir das amostras;
* ``classificador`` — o modelo em uso no reconhecimento ao vivo.

Gravação pelo site (Gestos → Gravar letras); treino pelo site ou pelo
comando ``treinar_alfabeto``.
"""
