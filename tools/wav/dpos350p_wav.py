# -*- coding: utf-8 -*-
"""Leitor do arquivo .wav do FNIRSI DPOS350P, baseado na engenharia reversa do firmware 2025-06-19.

O ".wav" NAO e um RIFF/WAVE: e um dump do serializador interno do firmware
(sub_40045714 grava, sub_400456f4 le). Todos os campos sao BIG-ENDIAN, inclusive as amostras.

Estrutura:
  0x00  7 x u32 BE  : [inicio_A, tam_A, inicio_B, tam_B, inicio_C, tam_C, total]
  A (0x32...)       : configuracoes (copia de campos da struct global G=0x40544e68)
  B                 : u16 W, u16 H, W*H u16 RGB565 = miniatura da tela (203x138) mostrada no navegador do aparelho
  C                 : amostras u16 BE -> CH1 (N amostras, se ativo) e depois CH2 (N, se ativo)

Uso:
  python dpos350p_wav.py arquivo.wav [mais.wav ...] [--dump] [--csv] [--plot [--html]] [--resumo resumo.csv]
"""
import argparse
import os
import struct
import sys

import numpy as np

import dpos350p_medidas as med

# Offsets dentro do arquivo (secao A). Validos enquanto o contador G+0x5d0 (offset 0x1a4)
# so afeta campos depois de 0x26a, e todos os campos abaixo vem antes disso.
# formato: nome -> (offset_no_arquivo, struct_fmt, campo na struct global)
CAMPOS = {
    "largura_tela_px":     (0x036, ">H", "G+0x008"),
    "altura_tela_px":      (0x038, ">H", "G+0x00a"),
    "px_por_div_h":        (0x04a, ">H", "G+0x01c"),
    "div_h":               (0x04c, ">H", "G+0x01e"),
    "px_por_div_v":        (0x04e, ">H", "G+0x020"),
    "div_v":               (0x050, ">H", "G+0x022"),
    "ch1_ativo":           (0x065, ">B", "G+0x03e"),
    "ch1_ponta_idx":       (0x067, ">B", "G+0x040"),  # 0=x1, 1=x10, 2=x100
    "ch1_vdiv_idx":        (0x068, ">B", "G+0x041"),  # 0=20V ... 12=2mV (ponta x1)
    "ch1_offset_dac":      (0x06a, ">H", "G+0x044"),
    "ch1_vdiv_uV":         (0x06d, ">Q", "G+0x050"),  # V/div em microvolts, ja com a ponta
    "ch1_posicao_px":      (0x07d, ">i", "G+0x060"),  # nivel de terra, em px a partir de baixo
    "ch1_vdiv_hw_uV":      (0x085, ">Q", "G+0x0d8"),
    "ch1_cod_por_div":     (0x08d, ">I", "G+0x0e0"),  # codigos de ADC (8 bit) por divisao
    "ch2_ativo":           (0x0a6, ">B", "G+0x102"),
    "ch2_ponta_idx":       (0x0a8, ">B", "G+0x104"),
    "ch2_vdiv_idx":        (0x0a9, ">B", "G+0x105"),
    "ch2_offset_dac":      (0x0ab, ">H", "G+0x108"),
    "ch2_vdiv_uV":         (0x0ae, ">Q", "G+0x110"),
    "ch2_posicao_px":      (0x0be, ">i", "G+0x120"),
    "ch2_vdiv_hw_uV":      (0x0c6, ">Q", "G+0x198"),
    "ch2_cod_por_div":     (0x0ce, ">I", "G+0x1a0"),
    "n_canais_ativos":     (0x0da, ">B", "G+0x1b0"),  # o "byte 218" do script antigo
    "shift_resolucao":     (0x0e0, ">I", "G+0x1bc"),
    "fator_resolucao":     (0x0e4, ">I", "G+0x1c0"),  # = 1 << shift; amostra = px * fator
    "gatilho_modo":        (0x0fe, ">B", "G+0x27a"),  # 0=Auto, 1=Single, 2=Normal
    "gatilho_borda":       (0x0ff, ">B", "G+0x27b"),  # 0=subida, 1=descida
    "gatilho_canal":       (0x100, ">B", "G+0x27c"),  # 0=CH1, 1=CH2
    "gatilho_nivel_px":    (0x101, ">h", "G+0x27e"),  # px a partir da base, mesma escala da posicao
    "supressao_hf":        (0x21e, ">B", "G+0x284"),  # 0..3 (menu "HF suppression"; valores nao mapeados)
    "zoom_ativo":          (0x11d, ">B", "G+0x2aa"),
    "n_amostras":          (0x120, ">I", "G+0x2b0"),
    "desloc_h":            (0x17e, ">q", "G+0x570"),  # / base_tempo_ps = px horizontais do centro (+ = direita)
    "base_tempo_idx":      (0x18f, ">B", "G+0x588"),
    "base_tempo_ps":       (0x190, ">Q", "G+0x590"),  # tempo/div em picossegundos
    "zoom_base_tempo_idx": (0x198, ">B", "G+0x598"),
    "zoom_base_tempo_ps":  (0x199, ">Q", "G+0x5a0"),
}

VDIV_TABELA_uV = [20_000_000, 10_000_000, 5_000_000, 2_000_000, 1_000_000, 500_000,
                  200_000, 100_000, 50_000, 20_000, 10_000, 5_000, 2_000]
PONTA = {0: 1, 1: 10, 2: 100}
MODO_GATILHO = {0: "Auto", 1: "Single", 2: "Normal"}
BORDA_GATILHO = {0: "subida", 1: "descida"}

# O ADC e entrelacado em 4 fases: amostras i%4 = 0..3 tem offsets proprios (~1 px nas bases lentas).
# Acima desta diferenca entre fases (em px) a correcao e aplicada.
ENTRELACAMENTO_MIN_PX = 0.3


def ler_arquivo(caminho):
    raw = open(caminho, "rb").read()
    if len(raw) < 0x130:
        raise ValueError(f"{caminho}: arquivo pequeno demais ({len(raw)} bytes)")

    ini_a, tam_a, ini_b, tam_b, ini_c, tam_c, total = struct.unpack_from(">7I", raw, 0)
    cab = dict(ini_a=ini_a, tam_a=tam_a, ini_b=ini_b, tam_b=tam_b,
               ini_c=ini_c, tam_c=tam_c, total=total)
    if total > len(raw) or ini_c + tam_c > len(raw):
        raise ValueError(f"{caminho}: cabecalho inconsistente {cab} (arquivo tem {len(raw)} bytes)")

    cfg = {nome: struct.unpack_from(fmt, raw, off)[0] for nome, (off, fmt, _) in CAMPOS.items()}

    n = cfg["n_amostras"]
    amostras = np.frombuffer(raw, dtype=">u2", count=tam_c // 2, offset=ini_c).astype(np.int64)
    canais = {}
    pos = 0
    for ch in ("ch1", "ch2"):
        if cfg[f"{ch}_ativo"]:
            canais[ch.upper()] = amostras[pos:pos + n]
            pos += n
    if pos != len(amostras):
        print(f"Aviso: secao C tem {len(amostras)} amostras, esperado {pos} "
              f"(N={n}, canais={list(canais)})", file=sys.stderr)
    return raw, cab, cfg, canais


def para_volts(amostras, cfg, ch):
    """Mesma escala dos cursores do firmware (sub_400317a8).

    As amostras sao a coordenada vertical na tela (px a partir de baixo) x fator_resolucao (64):
    0 = base do grafico, altura_tela_px*64 = topo (valores nesses extremos estao saturados).
    """
    ch = ch.lower()
    px = amostras / (cfg["fator_resolucao"] or (1 << cfg["shift_resolucao"]) or 1)
    ppd = cfg["px_por_div_v"] or 63
    return (px - cfg[f"{ch}_posicao_px"]) * (cfg[f"{ch}_vdiv_uV"] / 1e6) / ppd


def estimar_entrelacamento(amostras, cfg):
    """Estima o offset de cada fase (i % 4) do ADC entrelacado, em px.

    A estimativa usa a segunda diferenca r[i] = x[i] - (x[i-1] + x[i+1]) / 2, que remove o
    conteudo lento do sinal. Para um padrao periodico o_k, a media de r na fase k vale
    o_k - (o_{k-1} + o_{k+1}) / 2; na DFT de 4 pontos isso e multiplicar o harmonico m por
    1 - cos(pi m / 2), que se inverte para m = 1, 2, 3 (o m = 0 e o nivel DC, que nao e offset).

    Retorna (offsets_px, erro_padrao_px).
    """
    fator = cfg["fator_resolucao"] or 64
    topo = (cfg["altura_tela_px"] or 503) * fator
    x = amostras.astype(np.float64)
    r = x[1:-1] - (x[:-2] + x[2:]) / 2
    ok = (x[:-2] > 0) & (x[:-2] < topo) & (x[1:-1] > 0) & (x[1:-1] < topo) & (x[2:] > 0) & (x[2:] < topo)
    fase = np.arange(1, len(x) - 1) % 4
    R = np.zeros(4)
    ep = np.zeros(4)
    for k in range(4):
        sel = r[(fase == k) & ok]
        if len(sel) < 100:
            return None, None
        R[k] = sel.mean()
        ep[k] = sel.std() / np.sqrt(len(sel))
    Rf = np.fft.fft(R)
    lam = 1 - np.cos(np.pi * np.arange(4) / 2)
    Of = np.zeros(4, complex)
    Of[1:] = Rf[1:] / lam[1:]
    offs = np.real(np.fft.ifft(Of))
    return offs / fator, float(ep.max() / fator)


def corrigir_entrelacamento(amostras, cfg):
    """Remove o offset proprio de cada uma das 4 fases do ADC entrelacado.

    Retorna (amostras_corrigidas, offsets_px). Se a diferenca entre fases for menor que
    ENTRELACAMENTO_MIN_PX ou nao for estatisticamente significativa (5 erros-padrao),
    devolve as amostras originais e offsets None. Amostras saturadas nao sao alteradas.
    """
    fator = cfg["fator_resolucao"] or 64
    topo = (cfg["altura_tela_px"] or 503) * fator
    validas = (amostras > 0) & (amostras < topo)
    offs_px, ep = estimar_entrelacamento(amostras, cfg)
    if offs_px is None:
        return amostras, None
    espalho = offs_px.max() - offs_px.min()
    if espalho < ENTRELACAMENTO_MIN_PX or espalho < 5 * ep:
        return amostras, None
    offs = offs_px * fator
    corr = amostras.astype(np.float64)
    for k in range(4):
        corr[k::4][validas[k::4]] -= offs[k]
    return corr, offs / fator


def gatilho(cfg, dt):
    """Configuracao do gatilho e indice do ponto de disparo (t = 0) no registro."""
    n = cfg["n_amostras"]
    ch = "ch2" if cfg["gatilho_canal"] else "ch1"
    tb = cfg["zoom_base_tempo_ps"] if cfg["zoom_ativo"] else cfg["base_tempo_ps"]
    desloc_px = cfg["desloc_h"] / tb if tb else 0.0
    largura = cfg["largura_tela_px"] or 950
    g = {
        "modo": MODO_GATILHO.get(cfg["gatilho_modo"], cfg["gatilho_modo"]),
        "borda": BORDA_GATILHO.get(cfg["gatilho_borda"], cfg["gatilho_borda"]),
        "canal": ch.upper(),
        "nivel_V": (cfg["gatilho_nivel_px"] - cfg[f"{ch}_posicao_px"]) * (cfg[f"{ch}_vdiv_uV"] / 1e6)
                   / (cfg["px_por_div_v"] or 63),
        "desloc_px": desloc_px,
        # N amostras ocupam a largura da tela; o disparo fica no centro + deslocamento horizontal
        "indice": n / 2 + desloc_px * n / largura,
    }
    g["desloc_s"] = (g["indice"] - n / 2) * dt if dt else None
    return g


def miniatura(raw, cab):
    """Secao B: miniatura RGB565 da tela no momento da gravacao -> array (H, W, 3) uint8, ou None."""
    if cab["tam_b"] < 4:
        return None
    w, h = struct.unpack_from(">HH", raw, cab["ini_b"])
    if not w or not h or 4 + 2 * w * h > cab["tam_b"]:
        return None
    p = np.frombuffer(raw, dtype=">u2", count=w * h, offset=cab["ini_b"] + 4).reshape(h, w).astype(np.uint32)
    r = ((p >> 11) & 31) * 255 // 31
    g = ((p >> 5) & 63) * 255 // 63
    b = (p & 31) * 255 // 31
    return np.dstack([r, g, b]).astype(np.uint8)


def png_bytes(rgb, escala=1):
    """PNG sem dependencias externas."""
    import zlib
    if escala > 1:
        rgb = rgb.repeat(escala, 0).repeat(escala, 1)
    h, w, _ = rgb.shape
    dados = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def bloco(tipo, d):
        return struct.pack(">I", len(d)) + tipo + d + struct.pack(">I", zlib.crc32(tipo + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(dados, 9)) + bloco(b"IEND", b""))


def saturadas(amostras, cfg):
    """Fracao de amostras no limite da tela (sinal cortado)."""
    topo = (cfg["altura_tela_px"] or 503) * (cfg["fator_resolucao"] or 64)
    return float(np.mean((amostras <= 0) | (amostras >= topo)))


def dt_amostra(cfg):
    """Intervalo entre amostras: N amostras cobrem as div_h divisoes (confirmado com tons de 440/220 Hz)."""
    tb = cfg["zoom_base_tempo_ps"] if cfg["zoom_ativo"] else cfg["base_tempo_ps"]
    n = cfg["n_amostras"]
    if not tb or not n:
        return None
    return tb * 1e-12 * (cfg["div_h"] or 10) / n


def fmt_si(v, unidade):
    for fator, pref in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "µ"),
                        (1e-9, "n"), (1e-12, "p")):
        if abs(v) >= fator:
            return f"{v / fator:.4g} {pref}{unidade}"
    return f"{v:g} {unidade}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arquivos", nargs="+")
    ap.add_argument("--dump", action="store_true", help="mostra todos os campos decodificados")
    ap.add_argument("--csv", action="store_true", help="exporta <nome>_onda.csv")
    ap.add_argument("--plot", action="store_true", help="plota com plotly")
    ap.add_argument("--html", action="store_true", help="com --plot, salva <nome>_onda.html em vez de abrir o navegador")
    ap.add_argument("--resumo", metavar="CSV", help="grava as medicoes de todos os arquivos num CSV (;)")
    ap.add_argument("--miniatura", action="store_true", help="salva <nome>_tela.png (miniatura da tela gravada)")
    ap.add_argument("--bruto", action="store_true", help="nao corrige o offset do ADC entrelacado (4 fases)")
    a = ap.parse_args()

    linhas_resumo = []
    for caminho in a.arquivos:
        raw, cab, cfg, canais = ler_arquivo(caminho)
        print(f"\n=== {caminho} ({len(raw)} bytes)")
        print("cabecalho:", {k: hex(v) for k, v in cab.items()})
        if a.dump:
            for nome, (off, fmt, g) in CAMPOS.items():
                print(f"  0x{off:03x} {g:8s} {nome:22s} = {cfg[nome]}")

        dt = dt_amostra(cfg)
        trig = gatilho(cfg, dt)
        info = info_aquisicao(cfg, dt, trig)
        print("  ".join(f"{k}: {v}" for k, v in info.items()))

        resultados, medidas = {}, {}
        for ch, adc in canais.items():
            sat = saturadas(adc, cfg)
            if not a.bruto:
                adc_corr, offs = corrigir_entrelacamento(adc, cfg)
                if offs is not None:
                    print(f"  {ch}: offset do ADC entrelacado corrigido (fases 0-3: "
                          f"{', '.join(f'{o:+.2f}' for o in offs)} px; use --bruto para desligar)")
                    adc = adc_corr
            v = para_volts(adc, cfg, ch)
            resultados[ch] = v
            medidas[ch] = med.medir_canal(v, dt, sat)
        par = None
        if len(resultados) == 2:
            m1 = medidas["CH1"]
            par = med.medir_par(resultados["CH1"], resultados["CH2"], dt, m1["freq_Hz"] or m1["freq_FFT_Hz"])
        imprimir_medidas(medidas, par)
        for ch, m in medidas.items():
            if m["saturacao_%"] > 0.1:
                print(f"  aviso {ch}: {m['saturacao_%']:.1f}% das amostras no limite da tela "
                      f"(sinal cortado; Vmax/Vmin/Vpp ficam subestimados)")
        linhas_resumo.extend(linhas_csv_resumo(caminho, info, medidas, par))

        if a.csv and resultados:
            import csv
            nome_csv = os.path.splitext(caminho)[0] + "_onda.csv"
            n = max(len(v) for v in resultados.values())
            with open(nome_csv, "w", newline="") as f:
                w = csv.writer(f)
                # t = 0 no ponto de disparo
                w.writerow(["amostra", "t_s"] + [f"{ch}_V" for ch in resultados])
                for i in range(n):
                    w.writerow([i, "" if dt is None else f"{(i - trig['indice']) * dt:.6e}"] +
                               [f"{v[i]:.6g}" if i < len(v) else "" for v in resultados.values()])
            print("CSV:", nome_csv)

        tela = miniatura(raw, cab)
        if a.miniatura and tela is not None:
            nome_png = os.path.splitext(caminho)[0] + "_tela.png"
            with open(nome_png, "wb") as f:
                f.write(png_bytes(tela, 2))
            print("PNG:", nome_png)

        if a.plot and resultados:
            fig = figura(caminho, cfg, dt, info, trig, tela, resultados, medidas, par)
            if a.html:
                nome_html = os.path.splitext(caminho)[0] + "_onda.html"
                fig.write_html(nome_html, include_plotlyjs="cdn")
                print("HTML:", nome_html)
            else:
                fig.show()

    if a.resumo and linhas_resumo:
        import csv
        chaves = list(dict.fromkeys(k for l in linhas_resumo for k in l))
        with open(a.resumo, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=chaves, delimiter=";")
            w.writeheader()
            w.writerows(linhas_resumo)
        print(f"\nResumo ({len(linhas_resumo)} linhas): {a.resumo}")


CORES = {"CH1": "#f5d33b", "CH2": "#3bc8f5"}   # amarelo/ciano, como na tela do aparelho


def info_aquisicao(cfg, dt, trig):
    tb = (cfg["zoom_base_tempo_ps"] if cfg["zoom_ativo"] else cfg["base_tempo_ps"]) * 1e-12
    n = cfg["n_amostras"]
    info = {"Base de tempo": f"{fmt_si(tb, 's')}/div", "Amostras/canal": f"{n}"}
    if dt:
        info["Taxa"] = f"{fmt_si(1 / dt, 'S/s')}"
        info["Δt"] = f"{fmt_si(dt, 's')}"
        info["Duração"] = f"{fmt_si(n * dt, 's')}"
    info["Gatilho"] = (f"{trig['modo']}, {trig['canal']}, {trig['borda']}, "
                       f"{fmt_si(trig['nivel_V'], 'V') if trig['nivel_V'] else '0 V'}")
    if trig["desloc_s"]:
        info["Desloc. horizontal"] = fmt_si(trig["desloc_s"], "s")
    for ch in ("ch1", "ch2"):
        if cfg[f"{ch}_ativo"]:
            vdiv = cfg[f"{ch}_vdiv_uV"] / 1e6
            lsb = vdiv / (cfg["px_por_div_v"] or 63) / (cfg["fator_resolucao"] or 64)
            info[ch.upper()] = (f"{fmt_si(vdiv, 'V')}/div, ponta x{PONTA.get(cfg[ch + '_ponta_idx'], '?')}, "
                                f"LSB {fmt_si(lsb, 'V')}, faixa {fmt_si(vdiv * (cfg['div_v'] or 8), 'V')}")
    return info


def imprimir_medidas(medidas, par):
    chs = list(medidas)
    print(f"  {'':20s}" + "".join(f"{ch:>18s}" for ch in chs))
    for nome, chave, un in med.ROTULOS:
        print(f"  {nome:20s}" + "".join(f"{med.fmt(medidas[ch].get(chave), un):>18s}" for ch in chs))
    if par:
        for nome, chave, un in med.ROTULOS_PAR:
            print(f"  {nome:20s}{med.fmt(par.get(chave), un):>18s}")


def linhas_csv_resumo(caminho, info, medidas, par):
    linhas = []
    for ch, m in medidas.items():
        l = {"arquivo": os.path.basename(caminho), "canal": ch,
             "base_tempo": info["Base de tempo"], "config_canal": info.get(ch, ""), "gatilho": info["Gatilho"]}
        for _, chave, _ in med.ROTULOS:
            x = m.get(chave)
            l[chave] = "" if x is None else (f"{x:.6g}" if isinstance(x, float) else x)
        if par:
            for _, chave, _ in med.ROTULOS_PAR:
                x = par.get(chave)
                l[chave] = "" if x is None else f"{x:.6g}"
        linhas.append(l)
    return linhas


def figura(caminho, cfg, dt, info, trig, tela, resultados, medidas, par):
    import base64
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    chs = list(resultados)
    fig = make_subplots(
        rows=2, cols=2, column_widths=[0.68, 0.32], row_heights=[0.62, 0.38],
        specs=[[{"type": "xy"}, {"type": "table"}], [{"type": "xy"}, {"type": "xy"}]],
        subplot_titles=("Forma de onda (t = 0 no disparo)", "Medições", "Espectro (FFT, janela de Hann)",
                        "Tela do aparelho (miniatura gravada)"),
        horizontal_spacing=0.04, vertical_spacing=0.08)

    for ch, v in resultados.items():
        x = (np.arange(len(v)) - trig["indice"]) * dt if dt else np.arange(len(v))
        fig.add_trace(go.Scattergl(x=x, y=v, mode="lines", name=ch, line=dict(width=1, color=CORES[ch]),
                                   legendgroup=ch), row=1, col=1)
        if dt:
            f, amp = med.espectro(v, dt)
            dbv = 20 * np.log10(np.maximum(amp, 1e-9))
            fig.add_trace(go.Scattergl(x=f[1:], y=dbv[1:], mode="lines", name=f"{ch} FFT", showlegend=False,
                                       line=dict(width=1, color=CORES[ch]), legendgroup=ch), row=2, col=1)
        m = medidas[ch]
        for nivel, nome in ((m["Vtopo"], "topo"), (m["Vbase"], "base"), (m["Vmed"], "média")):
            fig.add_hline(y=nivel, line=dict(color=CORES[ch], width=0.8, dash="dot"), opacity=0.5, row=1, col=1)

    # ponto de disparo e nivel do gatilho
    if dt:
        fig.add_vline(x=0, line=dict(color="#ff8c1a", width=1, dash="dash"), row=1, col=1)
    if trig["canal"] in resultados:
        fig.add_hline(y=trig["nivel_V"], line=dict(color="#ff8c1a", width=1, dash="dash"),
                      annotation_text=f"T {fmt_si(trig['nivel_V'], 'V') if trig['nivel_V'] else '0 V'}",
                      annotation_font_color="#ff8c1a", row=1, col=1)

    if tela is not None:
        uri = "data:image/png;base64," + base64.b64encode(png_bytes(tela)).decode()
        fig.add_trace(go.Image(source=uri, hoverinfo="skip"), row=2, col=2)
        fig.update_xaxes(visible=False, row=2, col=2)
        fig.update_yaxes(visible=False, row=2, col=2)

    # tabela: informacoes da aquisicao + medicoes
    geral = {k: v for k, v in info.items() if k not in ("CH1", "CH2")}
    nomes = list(geral) + ["Configuração"] + [n for n, _, _ in med.ROTULOS]
    colunas = []
    for i, ch in enumerate(chs):
        col = [v if i == 0 else "" for v in geral.values()] + [info.get(ch, "")]
        col += [med.fmt(medidas[ch].get(c), u) for _, c, u in med.ROTULOS]
        colunas.append(col)
    if par:
        nomes += [n for n, _, _ in med.ROTULOS_PAR]
        colunas[0] += [med.fmt(par.get(c), u) for _, c, u in med.ROTULOS_PAR]
        for i in range(1, len(colunas)):
            colunas[i] += [""] * len(med.ROTULOS_PAR)
    fig.add_trace(go.Table(
        columnwidth=[1.3] + [1.6] * len(chs),
        header=dict(values=["<b>Parâmetro</b>"] + [f"<b>{ch}</b>" for ch in chs],
                    fill_color="#2b2f36", font=dict(color="white", size=12), align="left"),
        cells=dict(values=[nomes] + colunas, fill_color="#1b1e23", font=dict(color="#ddd", size=11),
                   align="left", height=22)), row=1, col=2)

    fig.update_xaxes(title_text="tempo (s)" if dt else "amostra", row=1, col=1)
    fig.update_yaxes(title_text="V", row=1, col=1)
    fig.update_xaxes(title_text="frequência (Hz)", type="log", row=2, col=1)
    fig.update_yaxes(title_text="dBV (pico)", row=2, col=1)
    fig.update_layout(title=f"FNIRSI DPOS350P — {os.path.basename(caminho)}", template="plotly_dark",
                      height=1000, hovermode="x unified", legend=dict(orientation="h", y=1.04, x=0))
    return fig


if __name__ == "__main__":
    main()
