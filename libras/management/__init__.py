"""Comandos de gerenciamento do LibrAI."""
import sys


def saida_segura():
    """Evita UnicodeEncodeError quando o console não suporta Unicode.

    O Windows às vezes codifica a saída em cp1252 (principalmente ao
    redirecionar), o que derrubaria comandos com caracteres como
    ✓/✗/→. Com ``errors="replace"`` o pior caso é um "?" impresso —
    no console UTF-8 real os símbolos continuam perfeitos.
    """
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
