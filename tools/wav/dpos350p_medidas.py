# -*- coding: utf-8 -*-
"""Medicoes de osciloscopio sobre as formas de onda lidas por dpos350p_wav.

Todas as medicoes usam o registro inteiro. Os niveis de referencia (10/50/90 %) sao calculados
sobre topo/base, como fazem os osciloscopios.
"""
import numpy as np

# fracao minima de amostras num pico do histograma para ele valer como topo/base (senao usa max/min)
LIMIAR_PATAMAR = 0.05
N_HARMONICAS = 10
# acima desta variacao do periodo (desvio/periodo) o sinal e tratado como nao periodico:
# frequencia por cruzamentos, duty e larguras deixam de fazer sentido (vale a da FFT)
JITTER_MAX = 0.20


def _topo_base(v):
    """Topo e base pelo histograma quando ha dois patamares (onda quadrada/pulso); senao max/min.

    Com um patamar so (ex.: trem de pulsos curtos sobre a linha de base), usar o histograma
    poria a linha de base como "topo" e inventaria overshoot.
    """
    vmin, vmax = float(v.min()), float(v.max())
    if vmax == vmin:
        return vmax, vmin
    hist, bordas = np.histogram(v, bins=256, range=(vmin, vmax))
    centros = (bordas[:-1] + bordas[1:]) / 2
    meio = len(hist) // 2
    alto, baixo = hist[meio:], hist[:meio]
    if min(alto.max(), baixo.max()) > LIMIAR_PATAMAR * len(v):
        return float(centros[meio + np.argmax(alto)]), float(centros[np.argmax(baixo)])
    return vmax, vmin


def _cruzamentos(v, nivel, histerese):
    """Indices (fracionarios) das bordas de subida e descida em 'nivel', com histerese."""
    sobe, desce = [], []
    estado = v[0] > nivel
    alto, baixo = nivel + histerese, nivel - histerese
    ultimo = 0
    for i in range(1, len(v)):
        x = v[i]
        if not estado and x > alto:
            estado = True
            sobe.append(_interp(v, ultimo, i, nivel))
        elif estado and x < baixo:
            estado = False
            desce.append(_interp(v, ultimo, i, nivel))
        if (x > nivel) != (v[i - 1] > nivel):
            ultimo = i - 1
    return np.array(sobe), np.array(desce)


def _interp(v, i0, i1, nivel):
    """Posicao fracionaria onde v cruza 'nivel' entre i0 e i1 (procura o ultimo par que cruza)."""
    for i in range(i1, i0, -1):
        a, b = v[i - 1], v[i]
        if (a - nivel) * (b - nivel) <= 0 and a != b:
            return i - 1 + (nivel - a) / (b - a)
    return float(i1)


def _tempos_borda(v, bordas, n10, n90, subida, janela):
    """Tempo medio 10%-90% (em amostras) nas bordas dadas."""
    t = []
    for b in bordas:
        c = int(round(b))
        i0, i1 = max(c - janela, 1), min(c + janela, len(v) - 1)
        seg = v[i0:i1]
        if subida:
            a = np.where(seg <= n10)[0]
            z = np.where(seg >= n90)[0]
        else:
            a = np.where(seg >= n90)[0]
            z = np.where(seg <= n10)[0]
        if len(a) == 0 or len(z) == 0:
            continue
        ini = a[a < (c - i0)]
        fim = z[z > (c - i0)]
        if len(ini) and len(fim):
            t.append(fim[0] - ini[-1])
    return float(np.mean(t)) if t else None


def espectro(v, dt):
    """FFT com janela de Hann. Retorna frequencias (Hz) e amplitude de pico (V) por componente."""
    x = v - v.mean()
    w = np.hanning(len(x))
    amp = np.abs(np.fft.rfft(x * w)) * 2 / w.sum()
    return np.fft.rfftfreq(len(x), dt), amp


def _pico_fft(f, amp):
    k = int(np.argmax(amp[1:]) + 1)
    if 1 <= k < len(amp) - 1:
        a, b, c = amp[k - 1], amp[k], amp[k + 1]
        den = a - 2 * b + c
        d = 0.5 * (a - c) / den if den else 0.0
    else:
        d = 0.0
    return (k + d) * (f[1] - f[0]), k


def medir_canal(v, dt, sat=0.0):
    """Dicionario de medicoes de um canal (volts, segundos, Hz, %)."""
    m = {}
    n = len(v)
    m["N"] = n
    m["Vmax"], m["Vmin"] = float(v.max()), float(v.min())
    m["Vpp"] = m["Vmax"] - m["Vmin"]
    m["Vmed"] = float(v.mean())
    m["Vrms"] = float(np.sqrt(np.mean(v ** 2)))
    ac = v - m["Vmed"]
    m["Vrms_AC"] = float(np.sqrt(np.mean(ac ** 2)))
    m["desvio_pad"] = m["Vrms_AC"]
    topo, base = _topo_base(v)
    m["Vtopo"], m["Vbase"] = topo, base
    m["Vamp"] = topo - base
    m["fator_crista"] = float(np.max(np.abs(ac)) / m["Vrms_AC"]) if m["Vrms_AC"] else None
    m["overshoot_%"] = 100 * (m["Vmax"] - topo) / m["Vamp"] if m["Vamp"] else None
    m["preshoot_%"] = 100 * (base - m["Vmin"]) / m["Vamp"] if m["Vamp"] else None
    m["saturacao_%"] = 100 * sat

    # espectro
    m["freq_FFT_Hz"] = m["THD_%"] = None
    m["harmonicas_V"] = []
    if dt and n > 16:
        f, amp = espectro(v, dt)
        f0, k0 = _pico_fft(f, amp)
        m["freq_FFT_Hz"] = f0
        m["fund_Vpico"] = float(amp[k0])
        harm = []
        for h in range(2, N_HARMONICAS + 1):
            kh = int(round(h * f0 / (f[1] - f[0])))
            if kh >= len(amp) - 1:
                break
            harm.append(float(amp[max(kh - 1, 0):kh + 2].max()))
        m["harmonicas_V"] = harm
        if amp[k0] > 0 and harm:
            m["THD_%"] = 100 * float(np.sqrt(np.sum(np.square(harm)))) / float(amp[k0])

    # tempo: cruzamentos no nivel de 50 % com histerese de 10 % da amplitude
    meio = (topo + base) / 2
    sobe, desce = _cruzamentos(v, meio, 0.1 * m["Vamp"]) if m["Vamp"] else (np.array([]), np.array([]))
    m["ciclos"] = max(len(sobe) - 1, 0)
    m["freq_Hz"] = m["periodo_s"] = m["duty_%"] = m["largura_pos_s"] = m["largura_neg_s"] = None
    m["t_subida_s"] = m["t_descida_s"] = m["jitter_periodo_s"] = None
    m["periodico"] = None
    if dt and len(sobe) >= 2:
        periodos = np.diff(sobe)
        per = float(np.mean(periodos))
        m["jitter_periodo_s"] = float(np.std(periodos)) * dt
        m["periodico"] = bool(np.std(periodos) <= JITTER_MAX * per)
        if not m["periodico"]:
            return m
        m["periodo_s"] = per * dt
        m["freq_Hz"] = 1 / m["periodo_s"]
        # largura positiva = de cada subida ate a descida seguinte
        larg = [desce[desce > s][0] - s for s in sobe[:-1] if np.any(desce > s)]
        if larg:
            lp = float(np.mean(larg))
            m["largura_pos_s"] = lp * dt
            m["largura_neg_s"] = (per - lp) * dt
            m["duty_%"] = 100 * lp / per
        n10 = base + 0.1 * m["Vamp"]
        n90 = base + 0.9 * m["Vamp"]
        janela = max(int(per / 2), 2)
        ts = _tempos_borda(v, sobe, n10, n90, True, janela)
        td = _tempos_borda(v, desce, n10, n90, False, janela)
        m["t_subida_s"] = ts * dt if ts is not None else None
        m["t_descida_s"] = td * dt if td is not None else None
    return m


def medir_par(v1, v2, dt, f_ref=None):
    """Relacao entre dois canais: atraso de CH2 em relacao a CH1, fase, correlacao, ganho."""
    n = min(len(v1), len(v2))
    a, b = v1[:n] - v1[:n].mean(), v2[:n] - v2[:n].mean()
    r = {}
    na, nb = np.sqrt(np.sum(a * a)), np.sqrt(np.sum(b * b))
    r["correlacao"] = float(np.sum(a * b) / (na * nb)) if na and nb else None
    r["ganho_CH2/CH1_dB"] = float(20 * np.log10(nb / na)) if na and nb else None
    # correlacao cruzada via FFT; atraso positivo = CH2 atrasado
    m = 1 << int(np.ceil(np.log2(2 * n)))
    xc = np.fft.irfft(np.fft.rfft(b, m) * np.conj(np.fft.rfft(a, m)), m)
    xc = np.concatenate((xc[-(n - 1):], xc[:n]))
    k = int(np.argmax(xc))
    d = 0.0
    if 0 < k < len(xc) - 1:
        y0, y1, y2 = xc[k - 1], xc[k], xc[k + 1]
        den = y0 - 2 * y1 + y2
        d = 0.5 * (y0 - y2) / den if den else 0.0
    lag = k - (n - 1) + d
    if abs(lag) < 0.05:     # abaixo da resolucao da interpolacao
        lag = 0.0
    r["atraso_s"] = lag * dt if dt else None
    r["fase_graus"] = None
    if dt and f_ref:
        fase = (lag * dt * f_ref * 360) % 360
        r["fase_graus"] = fase - 360 if fase > 180 else fase
    return r


# nome, chave, unidade (para tabela/terminal)
ROTULOS = [
    ("Amostras", "N", ""),
    ("Vmax", "Vmax", "V"), ("Vmin", "Vmin", "V"), ("Vpp", "Vpp", "V"),
    ("Vtopo", "Vtopo", "V"), ("Vbase", "Vbase", "V"), ("Amplitude", "Vamp", "V"),
    ("Vmédio (DC)", "Vmed", "V"), ("Vrms", "Vrms", "V"), ("Vrms AC", "Vrms_AC", "V"),
    ("Fator de crista", "fator_crista", ""),
    ("Overshoot", "overshoot_%", "%"), ("Preshoot", "preshoot_%", "%"),
    ("Periódico", "periodico", ""),
    ("Frequência", "freq_Hz", "Hz"), ("Freq. (FFT)", "freq_FFT_Hz", "Hz"),
    ("Período", "periodo_s", "s"), ("Jitter do período", "jitter_periodo_s", "s"),
    ("Ciclos completos", "ciclos", ""),
    ("Duty cycle", "duty_%", "%"), ("Largura +", "largura_pos_s", "s"), ("Largura −", "largura_neg_s", "s"),
    ("Subida 10–90%", "t_subida_s", "s"), ("Descida 90–10%", "t_descida_s", "s"),
    ("THD", "THD_%", "%"), ("Saturação", "saturacao_%", "%"),
]
ROTULOS_PAR = [
    ("Atraso CH2−CH1", "atraso_s", "s"), ("Fase CH2−CH1", "fase_graus", "°"),
    ("Correlação", "correlacao", ""), ("Ganho CH2/CH1", "ganho_CH2/CH1_dB", "dB"),
]


def fmt(v, unidade):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não (use a FFT)"
    if unidade in ("", "%", "°", "dB"):
        if isinstance(v, (int, np.integer)):
            return f"{v}"
        return f"{v:.4g}{(' ' + unidade) if unidade else ''}"
    for fator, pref in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "µ"),
                        (1e-9, "n"), (1e-12, "p")):
        if abs(v) >= fator:
            return f"{v / fator:.4g} {pref}{unidade}"
    return f"0 {unidade}"
