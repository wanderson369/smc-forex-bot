
SMC Forex Bot v5 — Metodologia Completa
==========================================
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
  - Stop Loss: abaixo/acima do OB/FVG
  - Take Profit: múltiplos de RR, ajustável
  - Breakeven: ao romper máxima/mínima recente
"""

import os, time, requests
from datetime import datetime, timezone, timedelta
from collections import deque

BRT = timezone(timedelta(hours=-3))  # Fuso horário Brasília

def agora_brt():
    return datetime.now(BRT).strftime("%d/%m %H:%M")

def converter_hora(dt_str):
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        dt_utc = dt.replace(tzinfo=timezone.utc)
        dt_brt = dt_utc.astimezone(BRT)
        return dt_brt.strftime("%d/%m %H:%M")
    except:
        return dt_str

# ============================================================
# CONFIGURAÇÕES
# ============================================================
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")
TWELVE_API_KEY   = os.environ.get("TWELVE_API_KEY", "SUA_CHAVE_AQUI")

# Todos pares Forex + USDT cripto
TODOS_PARES = {
    "EUR/USD": "EURUSD","GBP/USD": "GBPUSD","USD/JPY": "USDJPY",
    "USD/CHF": "USDCHF","AUD/USD": "AUDUSD","USD/CAD": "USDCAD",
    "NZD/USD": "NZDUSD","EUR/GBP": "EURGBP","EUR/JPY": "EURJPY",
    "GBP/JPY": "GBPJPY","AUD/JPY": "AUDJPY","CHF/JPY": "CHFJPY",
    "EUR/AUD": "EURAUD","EUR/CHF": "EURCHF","GBP/CHF": "GBPCHF",
    "AUD/CHF": "AUDCHF","NZD/JPY": "NZDJPY",
    # Cripto
    "BTC/USDT": "BTCUSDT","ETH/USDT": "ETHUSDT",
    "XRP/USDT": "XRPUSDT","BNB/USDT": "BNBUSDT"
}

CONFIG = {
    "velas_analisar":    80,
    "min_movimento_bos": 0.0003,
    "lg_sombra_ratio":   1.8,
    "pausado":           False,
    "timeframes_ativos": ["M1","M5","15min","1h","4h","D1"],
    "pares_ativos":      list(TODOS_PARES.keys()),
    "prob_minima":       58,
    "filtro_pares":      [],
    "filtro_direcao":    "",
    "filtro_prob":       58,
    "meus_favoritos":    [],
    "stop_loss":         0,      # automático calculado abaixo/OB/FVG
    "take_profit":       0       # múltiplo RR ajustável (1:5-1:10)
}

INTERVALOS = {"M1":60,"M5":300,"15min":900,"1h":3600,"4h":14400,"D1":86400}

sinais_enviados    = {}
historico_sinais   = deque(maxlen=200)
ultima_verificacao = {}
ultimo_update_id   = 0
inicio = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
total_sinais       = 0

# ============================================================
# Funções principais de busca, análise e alertas seguem
# (mantendo toda lógica SMC do v4.0, com ajuste para Stop Loss / Take Profit)
# ============================================================

# Exemplo de Stop Loss / Take Profit baseado no OB/FVG
def calcular_sl_tp(sinal):
    preco = sinal["preco"]
    if sinal["direcao"] == "COMPRA":
        sl = sinal["smc_principal"]["nivel"] - (preco*0.002)  # margem pequena
        tp = preco + (preco - sl)*5  # RR 1:5
    else:
        sl = sinal["smc_principal"]["nivel"] + (preco*0.002)
        tp = preco - (sl - preco)*5
    return sl, tp

# ============================================================
# O restante do código do Bot permanece igual ao SMC v4
# Só é necessário chamar calcular_sl_tp() antes de enviar o sinal
# e adicionar os campos "stop_loss" e "take_profit" no alerta
# ============================================================
