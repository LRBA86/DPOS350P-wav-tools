# -*- coding: utf-8 -*-
"""Testes do leitor e das medicoes do DPOS350P.

Rodar na pasta do projeto:  python -m pytest -q
Os testes com arquivos reais usam a pasta Ondas/ e sao pulados se ela nao existir.
"""
import glob
import os
import struct
import sys

import numpy as np
import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import dpos350p_medidas as med  # noqa: E402
import dpos350p_wav as d  # noqa: E402

ONDAS = os.path.join(RAIZ, "Ondas")
REAIS = sorted(glob.glob(os.path.join(ONDAS, "*.wav")))
precisa_reais = pytest.mark.skipif(not REAIS, reason="pasta Ondas/ sem arquivos .wav")


def onda(nome):
    return os.path.join(ONDAS, nome)


def volts(nome, corrigir=True):
    raw, cab, cfg, canais = d.ler_arquivo(onda(nome))
    out = {}
    for ch, a in canais.items():
        if corrigir:
            a, _ = d.corrigir_entrelacamento(a, cfg)
        out[ch] = d.para_volts(a, cfg, ch)
    return cfg, out


# ---------------------------------------------------------------- estrutura dos arquivos reais

@precisa_reais
@pytest.mark.parametrize("caminho", REAIS, ids=os.path.basename)
def test_cabecalho_e_tamanho(caminho):
    raw, cab, cfg, canais = d.ler_arquivo(caminho)
    assert cab["ini_a"] == 0x32
    assert cab["total"] == len(raw)
    assert cab["ini_b"] == cab["ini_a"] + cab["tam_a"]
    assert cab["ini_c"] == cab["ini_b"] + cab["tam_b"]
    assert cab["ini_c"] + cab["tam_c"] == cab["total"]
    assert cfg["n_canais_ativos"] == len(canais) == cfg["ch1_ativo"] + cfg["ch2_ativo"]
    assert cab["tam_c"] == 2 * cfg["n_amostras"] * len(canais)


@precisa_reais
@pytest.mark.parametrize("caminho", REAIS, ids=os.path.basename)
def test_amostras_dentro_da_tela(caminho):
    raw, cab, cfg, canais = d.ler_arquivo(caminho)
    topo = cfg["altura_tela_px"] * cfg["fator_resolucao"]
    for a in canais.values():
        assert a.min() >= 0 and a.max() <= topo


@precisa_reais
@pytest.mark.parametrize("caminho", REAIS, ids=os.path.basename)
def test_vdiv_coerente_com_tabela(caminho):
    raw, cab, cfg, canais = d.ler_arquivo(caminho)
    for ch in ("ch1", "ch2"):
        esperado = d.VDIV_TABELA_uV[cfg[f"{ch}_vdiv_idx"]] * d.PONTA[cfg[f"{ch}_ponta_idx"]]
        assert cfg[f"{ch}_vdiv_uV"] == esperado


@precisa_reais
def test_miniatura():
    raw, cab, cfg, canais = d.ler_arquivo(onda("1.wav"))
    img = d.miniatura(raw, cab)
    assert img.shape == (138, 203, 3)
    assert d.png_bytes(img).startswith(b"\x89PNG")


# ---------------------------------------------------------------- escala e tempo (valores conhecidos)

@precisa_reais
def test_sinal_ac_centrado_no_terra():
    # 1.wav: sinais AC; a media tem de cair perto de 0 V (escala = (px - posicao) * V/div / 63)
    cfg, v = volts("1.wav")
    assert abs(v["CH1"].mean()) < 0.2 and abs(v["CH2"].mean()) < 0.4


@precisa_reais
@pytest.mark.parametrize("nome,freq", [("16.wav", 440.1), ("20.wav", 221.2), ("17.wav", 130.6)])
def test_base_de_tempo_por_frequencia_conhecida(nome, freq):
    cfg, v = volts(nome)
    m = med.medir_canal(v["CH2"], d.dt_amostra(cfg))
    assert m["freq_FFT_Hz"] == pytest.approx(freq, rel=0.005)


@precisa_reais
@pytest.mark.parametrize("nome", ["16.wav", "17.wav", "18.wav", "19.wav", "20.wav", "21.wav"])
def test_disparo_no_indice_calculado(nome):
    raw, cab, cfg, canais = d.ler_arquivo(onda(nome))
    dt = d.dt_amostra(cfg)
    g = d.gatilho(cfg, dt)
    px = canais[g["canal"]] / cfg["fator_resolucao"]
    nivel = cfg["gatilho_nivel_px"]
    assert g["borda"] == "subida"
    cruz = np.where((px[:-1] < nivel) & (px[1:] >= nivel))[0]
    assert np.min(np.abs(cruz - g["indice"])) < 50


@precisa_reais
def test_nivel_gatilho_em_volts():
    # 21..24 usam o mesmo nivel (0,897 V) com posicoes diferentes do CH2
    for nome in ("21.wav", "24.wav"):
        raw, cab, cfg, canais = d.ler_arquivo(onda(nome))
        assert d.gatilho(cfg, d.dt_amostra(cfg))["nivel_V"] == pytest.approx(0.8968, abs=1e-3)


# ---------------------------------------------------------------- entrelacamento

@precisa_reais
def test_entrelacamento_detectado_nas_bases_lentas():
    raw, cab, cfg, canais = d.ler_arquivo(onda("1.wav"))
    _, offs = d.corrigir_entrelacamento(canais["CH2"], cfg)
    assert offs is not None and offs.max() - offs.min() > 1.0


@precisa_reais
def test_entrelacamento_nao_aplicado_em_audio():
    for nome in ("16.wav", "26.wav"):
        raw, cab, cfg, canais = d.ler_arquivo(onda(nome))
        for a in canais.values():
            assert d.corrigir_entrelacamento(a, cfg)[1] is None


def _cfg_sintetico():
    return {"fator_resolucao": 64, "altura_tela_px": 503}


def test_entrelacamento_recupera_padrao_injetado():
    rng = np.random.default_rng(1)
    n = 24000
    t = np.arange(n)
    sinal = 250 * 64 + 3000 * np.sin(2 * np.pi * t / 937) + rng.normal(0, 20, n)
    padrao = np.array([-60.0, 8.0, 50.0, 2.0])
    x = sinal + padrao[t % 4]
    corr, offs = d.corrigir_entrelacamento(x, _cfg_sintetico())
    assert offs is not None
    assert offs == pytest.approx((padrao - padrao.mean()) / 64, abs=0.05)
    assert np.std((corr - sinal) - (corr - sinal).mean()) < 2


def test_entrelacamento_ignora_ruido_puro():
    rng = np.random.default_rng(2)
    x = 250 * 64 + rng.normal(0, 3000, 24000)
    assert d.corrigir_entrelacamento(x, _cfg_sintetico())[1] is None


# ---------------------------------------------------------------- medicoes (sinais sinteticos)

def test_quadrada_duty_e_subida():
    dt = 1e-6
    t = np.arange(50000) * dt
    fase = (t * 1000) % 1
    v = np.minimum(np.clip(fase / 0.025, 0, 1), np.clip((0.3 - fase) / 0.025 + 1, 0, 1)) * 5
    m = med.medir_canal(v, dt)
    assert m["freq_Hz"] == pytest.approx(1000, rel=1e-3)
    assert m["duty_%"] == pytest.approx(30, abs=0.2)
    assert m["Vtopo"] == pytest.approx(5, abs=0.05) and m["Vbase"] == pytest.approx(0, abs=0.05)
    assert m["t_subida_s"] == pytest.approx(20e-6, abs=2e-6)   # 10-90 % de uma rampa de 25 us


def test_seno_vrms_e_thd():
    dt = 2e-5
    t = np.arange(47504) * dt
    f0 = 50 / (len(t) * dt)
    v = np.sin(2 * np.pi * f0 * t) + 0.1 * np.sin(2 * np.pi * 3 * f0 * t) + 0.05 * np.sin(2 * np.pi * 5 * f0 * t)
    m = med.medir_canal(v, dt)
    assert m["Vrms"] == pytest.approx(np.sqrt((1 + 0.01 + 0.0025) / 2), rel=1e-3)
    assert m["THD_%"] == pytest.approx(100 * np.hypot(0.1, 0.05), abs=0.1)
    assert m["freq_Hz"] == pytest.approx(f0, rel=1e-3)


def test_sinal_irregular_nao_reporta_frequencia_por_cruzamento():
    # seno com frequencia sorteada a cada 2 ms (50..500 Hz): cruza muito, mas sem periodo estavel
    rng = np.random.default_rng(3)
    dt = 1e-5
    f = np.repeat(rng.uniform(50, 500, 200), 200)
    v = np.sin(2 * np.pi * np.cumsum(f) * dt)
    m = med.medir_canal(v, dt)
    assert m["periodico"] is False and m["freq_Hz"] is None


def test_atraso_e_fase_entre_canais():
    dt = 1e-5
    t = np.arange(40000) * dt
    p = med.medir_par(np.sin(2 * np.pi * 50 * t), 0.5 * np.sin(2 * np.pi * 50 * (t - 1e-3)), dt, 50)
    assert p["atraso_s"] == pytest.approx(1e-3, abs=2e-5)
    assert p["fase_graus"] == pytest.approx(18, abs=0.5)
    assert p["ganho_CH2/CH1_dB"] == pytest.approx(-6.02, abs=0.05)


def test_trem_de_pulsos_sem_overshoot_falso():
    dt = 1e-5
    t = np.arange(40000)
    v = np.where((t % 1000) < 50, -20.0, 0.0)
    m = med.medir_canal(v, dt)
    assert m["overshoot_%"] == pytest.approx(0, abs=1e-6)
    assert m["freq_Hz"] == pytest.approx(100, rel=1e-3)
    assert m["duty_%"] == pytest.approx(95, abs=0.5)
