"""
gera_icone.py  --  Desenha o emissao.ico (espectro com um pico passando da
linha de limite). Rodar de novo so se quiser mudar o desenho:

    python gera_icone.py

Requer Pillow.
"""
import math
import os

from PIL import Image, ImageDraw

S = 1024                      # desenha grande e reduz, para suavizar
FUNDO, GRADE = (22, 33, 52), (52, 70, 100)
TRACE, LIMITE = (64, 224, 160), (255, 86, 74)


def espectro(x):
    """Altura (0..1) do trace em x (0..1): piso ondulado e tres picos."""
    y = 0.16 + 0.025 * math.sin(19 * x)
    for centro, altura, largura in ((0.22, 0.30, 0.035), (0.50, 0.66, 0.04),
                                    (0.78, 0.24, 0.035)):
        y += altura * math.exp(-((x - centro) / largura) ** 2)
    return y


def desenha():
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=S // 6, fill=FUNDO)
    m = S * 0.14              # margem da area do grafico
    x0, x1, y0, y1 = m, S - m, S - m, m
    for k in range(1, 4):     # grade
        gx = x0 + (x1 - x0) * k / 4
        gy = y1 + (y0 - y1) * k / 4
        d.line([gx, y1, gx, y0], fill=GRADE, width=S // 128)
        d.line([x0, gy, x1, gy], fill=GRADE, width=S // 128)

    def pt(x, y):
        return x0 + (x1 - x0) * x, y0 + (y1 - y0) * y

    # limite em degrau, como o das normas
    lim = [pt(0, 0.70), pt(0.40, 0.70), pt(0.40, 0.60), pt(1, 0.60)]
    d.line(lim, fill=LIMITE, width=S // 22, joint='curve')
    pts = [pt(i / 300.0, espectro(i / 300.0)) for i in range(301)]
    d.line(pts, fill=TRACE, width=S // 18, joint='curve')
    return img


if __name__ == '__main__':
    destino = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emissao.ico')
    desenha().resize((256, 256), Image.LANCZOS).save(
        destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
    print(destino)
