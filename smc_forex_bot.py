"""
SMC Forex Bot v4.0 — Metodologia Completa (SEM XAG/USD)
======================================================
Baseado no ebook SMC Trading Hub 2023

CONCEITOS IMPLEMENTADOS:
━━━━━━━━━━━━━━━━━━━━━━━
ESTRUTURA:
  - BOS (Break of Structure) — fechamento completo exigido
  - FBOS (Fake BOS) — detecção de falsos rompimentos
  - CHoCH (Change of Character) — com e sem IDM
  - Structure Mapping Bullish/Bearish

LIQUIDEZ:
  - EQH/EQL (Equal Highs/Equal Lows) — liquidez de retail
  - BSL/SSL (Buy/Sell Side Liquidity)
  - IDM (Inducement) — armadilha antes do real
  - SMT (Smart Money Trap)
  - Session Liquidity (Asian/London/NY)
  - PDH/PDL (Previous Day High/Low)
  - IFC Candle (Institutional Funding Candle)

ZONAS:
  - Order Block válido (com Imbalance + Liquidity Sweep)
  - Order Flow (mitigado vs não-mitigado)
  - FVG/Imbalance
  - Zonas Premium e Desconto (entrada correta)
  - POI/AOI (Price/Area of Interest)
  - Supply/Demand (Flip Zones D2S/S2D)

ENTRADAS:
  - CHoCH + IDM Entry
  - BOS Entry
  - FLiP Entry (D2S / S2D)
  - Single Candle Mitigation
  - Ping Pong Entries

CANDLES (complemento):
  - Pin Bar, Engolfo, Harami, Bebê Abandonado
  - Martelo, Estrela Cadente, Doji
  - Três Soldados, Três Corvos

GESTÃO:
  - Probabilidade baseada em confluência
  - Risk Management: 1-2% conta própria / 0.25-1% conta fondeada
  - RR alvo 1:5 a 1:10
"""

import os, time, requests
from datetime import datetime, timezone, timedelta
from collections import deque

# Fuso horário de Brasília (UTC-3)
BRT = timezone(timedelta(hours=-3))

def agora_brt():
    return datetime.now(BRT).strftime("%d/%m %H:%M")

def converter_hora(dt_str):
    """Converte horário da API (UTC) para Brasília"""
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        dt_utc = dt.replace(tzinfo=timezone.utc)
        dt_brt = dt_utc.astimezone(BRT)
        return dt_brt.strftime("%d/%m %H:%M")
    except:
        return dt_str

# ============================================================
# CONFIGURAÇÕES (XAG/USD REMOVIDO)
# ============================================================
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")
TWELVE_API_KEY   = os.environ.get("TWELVE_API_KEY", "SUA_CHAVE_AQUI")

# ✅ 16 PARES ATIVOS (XAG/USD REMOVIDO)
TODOS_PARES = {
    "EUR/USD": "EUR/USD", "GBP/USD": "GBP/USD", "USD/JPY": "USD/JPY",
    "AUD/USD": "AUD/USD", "USD/CHF": "USD/CHF", "USD/CAD": "USD/CAD",
    "NZD/USD": "NZD/USD", "GBP/CAD": "GBP/CAD",
    "EUR/GBP": "EUR/GBP", "EUR/JPY": "EUR/JPY", "GBP/JPY": "GBP/JPY",
    "AUD/JPY": "AUD/JPY", "EUR/AUD": "EUR/AUD", "GBP/AUD": "GBP/AUD",
    "XAU/USD": "XAU/USD",  # Ouro mantido
    "BTC/USDT": "BTC/USDT",
}

CONFIG = {
    "velas_analisar":    80,
    "min_movimento_bos": 0.0003,
    "lg_sombra_ratio":   1.8,
    "pausado":           False,
    "timeframes_ativos": ["15min", "1h"],
    "pares_ativos":      list(TODOS_PARES.keys()),
    "prob_minima":       58,
    "filtro_pares":      [],
    "filtro_direcao":    "",
    "filtro_prob":       58,
    "meus_favoritos":    [],
}

INTERVALOS = {"5min": 300, "15min": 900, "1h": 3600, "4h": 14400}

sinais_enviados    = {}
historico_sinais   = deque(maxlen=200)
ultima_verificacao = {}
ultimo_update_id   = 0
inicio = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
total_sinais       = 0

# ============================================================
# API TWELVE DATA
# ============================================================
def buscar_candles(par, timeframe, qtd=80):
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol": par, "interval": timeframe,
            "outputsize": qtd, "apikey": TWELVE_API_KEY, "format": "JSON",
        }, timeout=15)
        data = r.json()
        if data.get("status") == "error":
            return []
        return [{"open": float(v["open"]), "high": float(v["high"]),
                 "low": float(v["low"]), "close": float(v["close"]),
                 "datetime": v["datetime"]}
                for v in reversed(data.get("values", []))]
    except Exception as e:
        print(f"Erro API {par} {timeframe}: {e}")
        return []

# ============================================================
# UTILITÁRIOS DE CANDLE
# ============================================================
def info(v):
    corpo  = abs(v["close"] - v["open"])
    range_ = max(v["high"] - v["low"], 0.00001)
    return {
        "corpo": corpo, "range": range_,
        "ss": v["high"] - max(v["open"], v["close"]),
        "si": min(v["open"], v["close"]) - v["low"],
        "alta": v["close"] > v["open"],
        "baixa": v["close"] < v["open"],
        "cp": corpo / range_,
        "mid": (v["high"] + v["low"]) / 2,
    }

# ============================================================
# ZONAS PREMIUM E DESCONTO
# ============================================================
def zona_premium_desconto(candles, preco_atual):
    """
    Calcula se o preço está em zona Premium (acima de 50%) ou Desconto (abaixo de 50%)
    baseado no range das últimas 20 velas (equivalente ao range institucional)
    Premium = acima de 62% do range → vender
    Desconto = abaixo de 38% do range → comprar
    """
    ultimas = candles[-20:]
    maxima  = max(v["high"] for v in ultimas)
    minima  = min(v["low"]  for v in ultimas)
    range_  = maxima - minima
    if range_ == 0:
        return "NEUTRO", 50

    posicao = (preco_atual - minima) / range_ * 100

    if posicao >= 62:
        return "PREMIUM", posicao    # zona de venda
    elif posicao <= 38:
        return "DESCONTO", posicao   # zona de compra
    else:
        return "EQUILIBRIO", posicao # zona neutra (50%)

# ============================================================
# DETECÇÃO DE LIQUIDEZ
# ============================================================
def detectar_eqh_eql(candles):
    """EQH/EQL — Equal Highs/Lows — liquidez de retail acumulada"""
    if len(candles) < 10: return []
    sinais = []
    tolerancia = CONFIG["min_movimento_bos"] * 2

    maximas = [v["high"] for v in candles[-20:-1]]
    minimas = [v["low"]  for v in candles[-20:-1]]
    at      = candles[-1]

    # EQH — duas ou mais máximas iguais = liquidez acima
    for i in range(len(maximas)-3):
        for j in range(i+2, len(maximas)):
            if abs(maximas[i] - maximas[j]) <= tolerancia:
                nivel = (maximas[i] + maximas[j]) / 2
                if at["close"] > nivel:
                    sinais.append({
                        "padrao": "EQH Sweep", "dir": "VENDA",
                        "nivel": nivel, "prob_base": 68,
                        "desc": f"Equal Highs varridos em {nivel:.5f} — liquidez coletada, reversão provável"
                    })
                break

    # EQL — duas ou mais mínimas iguais = liquidez abaixo
    for i in range(len(minimas)-3):
        for j in range(i+2, len(minimas)):
            if abs(minimas[i] - minimas[j]) <= tolerancia:
                nivel = (minimas[i] + minimas[j]) / 2
                if at["close"] < nivel:
                    sinais.append({
                        "padrao": "EQL Sweep", "dir": "COMPRA",
                        "nivel": nivel, "prob_base": 68,
                        "desc": f"Equal Lows varridos em {nivel:.5f} — liquidez coletada, reversão provável"
                    })
                break

    return sinais

def detectar_pdh_pdl(candles):
    """PDH/PDL — Previous Day High/Low — liquidez diária"""
    if len(candles) < 30: return []
    sinais = []

    # Calcula high/low do "dia anterior" (últimas 24-48 velas como proxy)
    periodo_ant = candles[-48:-24]
    if not periodo_ant: return []

    pdh = max(v["high"] for v in periodo_ant)
    pdl = min(v["low"]  for v in periodo_ant)
    at  = candles[-1]
    mov = abs(at["close"] - at["open"])

    if at["close"] > pdh
