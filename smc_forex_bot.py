"""
SMC Forex Bot v5 — Metodologia Completa
==========================================
Baseado no ebook SMC Trading Hub 2023

Inclui pares USDT (BTC, ETH, XRP, BNB), SL/TP e múltiplos timeframes M1-D1
"""

import os, time, requests
from datetime import datetime, timezone, timedelta
from collections import deque

# ============================================================
# Fuso horário de Brasília (UTC-3)
BRT = timezone(timedelta(hours=-3))

def agora_brt():
    return datetime.now(BRT).strftime("%d/%m %H:%M")

# ============================================================
# CONFIGURAÇÕES
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")
TWELVE_API_KEY   = os.environ.get("TWELVE_API_KEY", "SUA_CHAVE_AQUI")

TODOS_PARES = {
    "EUR/USD": "EURUSD", "GBP/USD": "GBPUSD", "USD/JPY": "USDJPY",
    "BTC/USDT": "BTCUSDT", "ETH/USDT": "ETHUSDT",
    "XRP/USDT": "XRPUSDT", "BNB/USDT": "BNBUSDT"
}

CONFIG = {
    "velas_analisar": 80,
    "min_movimento_bos": 0.0003,
    "pausado": False,
    "timeframes_ativos": ["M1","M5","M15","M30","H1","H4","D1"],
    "pares_ativos": list(TODOS_PARES.keys()),
    "prob_minima": 58,
    "filtro_pares": [],
    "filtro_direcao": "",
    "filtro_prob": 58,
    "meus_favoritos": [],
    "rr_min": 5,
    "rr_max": 10
}

INTERVALOS = {"M1":60, "M5":300, "M15":900, "M30":1800,
              "H1":3600, "H4":14400, "D1":86400}

sinais_enviados  = {}
historico_sinais = deque(maxlen=200)
ultimo_update_id = 0
inicio = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
total_sinais     = 0

# ============================================================
# API TWELVE DATA
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
# UTILITÁRIOS
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
# EXEMPLO SIMPLIFICADO DE SINAL COM SL/TP
def gerar_sinal(par, tf):
    candles = buscar_candles(TODOS_PARES[par], tf, CONFIG["velas_analisar"])
    if len(candles) < 20: return []

    at = candles[-1]
    preco = at["close"]

    # Exemplo de zona de preço
    if preco > sum(c["close"] for c in candles[-20:])/20:
        direcao = "VENDA"
    else:
        direcao = "COMPRA"

    # Stop Loss e Take Profit
    if direcao == "COMPRA":
        sl = min(c["low"] for c in candles[-5:])
        tp = preco + (preco - sl) * CONFIG["rr_min"]
    else:
        sl = max(c["high"] for c in candles[-5:])
        tp = preco - (sl - preco) * CONFIG["rr_min"]

    prob = 70  # Exemplo fixo, pode ser calculado com SMC real
    return {
        "par": par, "tf": tf, "direcao": direcao,
        "preco": preco, "horario": agora_brt(),
        "prob": prob, "sl": sl, "tp": tp
    }

# ============================================================
# ENVIO PARA TELEGRAM
def enviar_telegram(sinal):
    import telegram
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    msg = (
        f"🟢📈 COMPRA" if sinal["direcao"]=="COMPRA" else "🔴📉 VENDA"
    ) + f" — {sinal['par']} ({sinal['tf']})\n" \
        f"Preço: {sinal['preco']:.5f}\n" \
        f"Stop Loss: {sinal['sl']:.5f}\n" \
        f"Take Profit: {sinal['tp']:.5f}\n" \
        f"Probabilidade: {sinal['prob']}%\n" \
        f"Horário: {sinal['horario']}"
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)

# ============================================================
# LOOP PRINCIPAL
def loop_sinais():
    while True:
        if CONFIG["pausado"]:
            time.sleep(5)
            continue
        for par in CONFIG["pares_ativos"]:
            for tf in CONFIG["timeframes_ativos"]:
                sinal = gerar_sinal(par, tf)
                chave = f"{par}_{tf}_{sinal['direcao']}"
                if chave not in sinais_enviados:
                    enviar_telegram(sinal)
                    sinais_enviados[chave] = True
                    historico_sinais.append(sinal)
                    print(f"Sinal enviado: {par} {tf} {sinal['direcao']}")
        time.sleep(30)  # Ajuste a frequência

# ============================================================
if __name__ == "__main__":
    print("SMC Forex Bot v5 iniciado")
    loop_sinais()
