"""Reproduz o eixo X do Bode como o firmware desenha (sub_40038388) e como deveria ser."""
import math, sys
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

def fmt(f):
    for d, u in ((1e6, 'M'), (1e3, 'k'), (1, '')):
        if f >= d:
            return f"{f / d:.3g}{u}"
    return f"{f:.3g}"

def firmware(ax, fi, ff):
    a, b = math.log10(fi), math.log10(ff)
    ndiv = 3                                     # S[0x0a] fixo
    for k in range(ndiv + 1):
        ax.axvline(k / ndiv, color='#bbb', lw=1.2)
    for k in range(ndiv):                        # menores em log10(2..9) DENTRO de cada divisao
        for m in range(2, 10):
            ax.axvline((k + math.log10(m)) / ndiv, color='#666', lw=0.6, ls=':')
    ticks = [k / ndiv for k in range(4)]         # 4 rotulos fixos
    ax.set_xticks(ticks, [fmt(10 ** (a + k * (b - a) / ndiv)) for k in range(4)])
    # onde estariam de verdade 20, 30, ..., 90 da primeira decada e as decadas
    for d in range(math.floor(a), math.ceil(b) + 1):
        for m in range(1, 10):
            f = m * 10 ** d
            if fi <= f <= ff:
                x = (math.log10(f) - a) / (b - a)
                ax.plot([x, x], [0, 0.12 if m > 1 else 0.3], color='#ff8c1a', lw=1.5 if m == 1 else 0.8)

def correto(ax, fi, ff):
    a, b = math.log10(fi), math.log10(ff)
    X = lambda f: (math.log10(f) - a) / (b - a)
    ticks, labels = [], []
    for d in range(math.floor(a), math.ceil(b) + 1):
        for m in range(1, 10):
            f = m * 10 ** d
            if fi * (1 - 1e-9) <= f <= ff * (1 + 1e-9):
                ax.axvline(X(f), color='#bbb' if m == 1 else '#666', lw=1.2 if m == 1 else 0.6, ls='-' if m == 1 else ':')
                if m == 1:
                    ticks.append(X(f)); labels.append(fmt(f))
    for f in (fi, ff):
        if all(abs(X(f) - t) > 0.03 for t in ticks):
            ticks.append(X(f)); labels.append(fmt(f))
    ax.set_xticks(ticks, labels)

faixas = [(10, 10_000), (10, 1_000_000), (100, 20_000), (50, 500_000)]
fig, axs = plt.subplots(len(faixas), 2, figsize=(13, 2.0 * len(faixas)))
for i, (fi, ff) in enumerate(faixas):
    for j, (fn, tit) in enumerate(((firmware, 'Firmware atual'), (correto, 'Correto (décadas reais)'))):
        ax = axs[i, j]
        fn(ax, fi, ff)
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_yticks([])
        ax.set_facecolor('#111')
        ax.set_title(f"{tit}: {fmt(fi)}Hz – {fmt(ff)}Hz ({math.log10(ff / fi):.2f} décadas)", fontsize=9)
fig.text(0.01, 0.005, "Laranja (esquerda): posição real de 1, 2, …, 9 × 10ⁿ Hz. Só coincidem com a grade do firmware quando a faixa tem exatamente 3 décadas.",
         fontsize=8)
plt.tight_layout(rect=(0, 0.02, 1, 1))
plt.savefig(sys.argv[1], dpi=90)
