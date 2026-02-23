"""
SMC Forex Bot v4.1 — Metodologia Completa
==========================================
Forex : 19 pares (Majors + Cruzamentos + Metais + NZD/USD + GBP/CAD)
Crypto: BTC, ETH, BNB, XRP, SOL
TFs   : M1, M5, M15, M30, H1, H4, D1
SMC   : BOS, FBOS, CHoCH, IDM, SMT, OB, FVG, FLiP, IFC, EQH/EQL, PDH/PDL, LG
Zonas : Premium e Desconto
Candles: Pin Bar, Engolfo, Harami, Bebê Abandonado, Martelo, Estrela, Doji, 3 Soldados, 3 Corvos
"""

import os, time, requests, threading
from datetime import datetime, timezone, timedelta
from collections import deque

# Fuso horário Brasília (UTC-3)
BRT = timezone(timedelta(hours=-3))

def agora_brt():
    return datetime.now(BRT).strftime("%d/%m %H:%M")

def converter_hora(dt_str):
    try:
        dt     = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        dt_utc = dt.replace(tzinfo=timezone.utc)
        dt_brt = dt_utc.astimezone(BRT)
        return dt_brt.strftime("%d/%m %H:%M")
    except:
        return dt_str

# ============================================================
# CONFIGURAÇÕES
# ============================================================
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")
TWELVE_API_KEY   = os.environ.get("TWELVE_API_KEY",   "SUA_CHAVE_AQUI")

PARES_FOREX = {
    "EUR/USD": "EUR/USD", "GBP/USD": "GBP/USD", "USD/JPY": "USD/JPY",
    "AUD/USD": "AUD/USD", "USD/CHF": "USD/CHF", "USD/CAD": "USD/CAD",
    "NZD/USD": "NZD/USD", "GBP/CAD": "GBP/CAD",
    "EUR/GBP": "EUR/GBP", "EUR/JPY": "EUR/JPY", "GBP/JPY": "GBP/JPY",
    "AUD/JPY": "AUD/JPY", "EUR/AUD": "EUR/AUD", "GBP/AUD": "GBP/AUD",
    "AUD/CHF": "AUD/CHF", "EUR/CHF": "EUR/CHF", "GBP/CHF": "GBP/CHF",
    "XAU/USD": "XAU/USD", "XAG/USD": "XAG/USD",
}

# Crypto com USDT (formato correto na Twelve Data)
PARES_CRYPTO = {
    "BTC/USDT": "BTC/USDT",
    "ETH/USDT": "ETH/USDT",
    "BNB/USDT": "BNB/USDT",
    "XRP/USDT": "XRP/USDT",
    "SOL/USDT": "SOL/USDT",
}

TODOS_PARES = {**PARES_FOREX, **PARES_CRYPTO}

CONFIG = {
    "velas_analisar":    80,
    "min_movimento_bos": 0.0001,
    "lg_sombra_ratio":   1.3,
    "pausado":           False,
    "timeframes_ativos": ["15min", "1h"],
    "pares_ativos":      list(TODOS_PARES.keys()),
    "prob_minima":       52,
    "filtro_pares":      [],
    "filtro_direcao":    "",
    "filtro_prob":       52,
    "meus_favoritos":    [],
}

INTERVALOS = {
    "1min":  60,    "5min":  300,  "15min": 900,
    "30min": 1800,  "1h":    3600, "4h":    14400,
    "1day":  86400,
}

TF_NOMES = {
    "1min": "M1", "5min": "M5", "15min": "M15", "30min": "M30",
    "1h": "H1", "4h": "H4", "1day": "D1",
}

sinais_enviados    = {}
historico_sinais   = deque(maxlen=200)
ultima_verificacao = {}
ultimo_update_id   = 0
inicio             = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
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
            print(f"  API erro {par}: {data.get('message','')}")
            return []
        return [{"open":  float(v["open"]),  "high": float(v["high"]),
                 "low":   float(v["low"]),   "close": float(v["close"]),
                 "datetime": v["datetime"]}
                for v in reversed(data.get("values", []))]
    except Exception as e:
        print(f"Erro API {par} {timeframe}: {e}")
        return []

# ============================================================
# UTILITÁRIOS
# ============================================================
def info(v):
    corpo  = abs(v["close"] - v["open"])
    range_ = max(v["high"] - v["low"], 0.00001)
    return {
        "corpo": corpo, "range": range_,
        "ss":    v["high"] - max(v["open"], v["close"]),
        "si":    min(v["open"], v["close"]) - v["low"],
        "alta":  v["close"] > v["open"],
        "baixa": v["close"] < v["open"],
        "cp":    corpo / range_,
    }

def mov_minimo(par):
    if "BTC" in par: return 50.0
    if "ETH" in par: return 5.0
    if "BNB" in par: return 1.0
    if "SOL" in par: return 0.5
    if "XRP" in par: return 0.001
    if "XAU" in par: return 0.5
    if "XAG" in par: return 0.05
    if "JPY" in par: return 0.05
    return CONFIG["min_movimento_bos"]

# ============================================================
# ZONAS PREMIUM E DESCONTO
# ============================================================
def zona_premium_desconto(candles, preco):
    ultimas = candles[-20:]
    maxima  = max(v["high"] for v in ultimas)
    minima  = min(v["low"]  for v in ultimas)
    range_  = maxima - minima
    if range_ == 0: return "NEUTRO", 50
    pos = (preco - minima) / range_ * 100
    if pos >= 62:   return "PREMIUM",    pos
    elif pos <= 38: return "DESCONTO",   pos
    else:           return "EQUILIBRIO", pos

# ============================================================
# DETECÇÕES SMC
# ============================================================
def detectar_bos(candles, par):
    if len(candles) < 22: return []
    sinais = []
    at  = candles[-1]
    mn  = mov_minimo(par)
    mov = abs(at["close"] - at["open"])
    maxima = max(v["high"] for v in candles[-21:-1])
    minima = min(v["low"]  for v in candles[-21:-1])
    if at["close"] > maxima:
        f = min(90, 62 + int(((at["close"] - maxima) / max(maxima, 0.0001)) * 8000))
        sinais.append({"padrao": "BOS", "sub": "ALTA", "dir": "COMPRA",
            "nivel": maxima, "prob_base": f,
            "desc": f"Rompimento bullish — fechamento acima de {maxima:.5f}"})
    if at["close"] < minima:
        f = min(90, 62 + int(((minima - at["close"]) / max(minima, 0.0001)) * 8000))
        sinais.append({"padrao": "BOS", "sub": "BAIXA", "dir": "VENDA",
            "nivel": minima, "prob_base": f,
            "desc": f"Rompimento bearish — fechamento abaixo de {minima:.5f}"})
    return sinais

def detectar_fbos(candles, par):
    if len(candles) < 12: return []
    sinais = []
    maxima = max(v["high"] for v in candles[-11:-2])
    minima = min(v["low"]  for v in candles[-11:-2])
    sp = candles[-2]; at = candles[-1]
    if sp["high"] > maxima and sp["close"] < maxima and at["close"] < sp["low"]:
        sinais.append({"padrao": "FBOS/SMT", "sub": "BEARISH", "dir": "VENDA",
            "nivel": maxima, "prob_base": 76,
            "desc": f"Fake BOS bearish em {maxima:.5f} — retail comprou, instituicao vendeu"})
    if sp["low"] < minima and sp["close"] > minima and at["close"] > sp["high"]:
        sinais.append({"padrao": "FBOS/SMT", "sub": "BULLISH", "dir": "COMPRA",
            "nivel": minima, "prob_base": 76,
            "desc": f"Fake BOS bullish em {minima:.5f} — retail vendeu, instituicao comprou"})
    return sinais

def detectar_choch(candles):
    if len(candles) < 8: return []
    sinais = []
    v1,v2,v3,v4,at = candles[-5],candles[-4],candles[-3],candles[-2],candles[-1]
    if v1["high"] < v2["high"] < v3["high"] and at["close"] < v4["low"]:
        idm  = v3["high"] < v2["high"]
        prob = 78 if idm else 68
        tipo = "com IDM" if idm else "sem IDM"
        sinais.append({"padrao": "CHoCH", "sub": f"BEARISH {tipo}", "dir": "VENDA",
            "nivel": v4["low"], "prob_base": prob,
            "desc": f"Mudanca de carater bearish ({tipo}) — rompeu {v4['low']:.5f}"})
    if v1["low"] > v2["low"] > v3["low"] and at["close"] > v4["high"]:
        idm  = v3["low"] > v2["low"]
        prob = 78 if idm else 68
        tipo = "com IDM" if idm else "sem IDM"
        sinais.append({"padrao": "CHoCH", "sub": f"BULLISH {tipo}", "dir": "COMPRA",
            "nivel": v4["high"], "prob_base": prob,
            "desc": f"Mudanca de carater bullish ({tipo}) — rompeu {v4['high']:.5f}"})
    return sinais

def detectar_idm(candles):
    if len(candles) < 8: return []
    sinais = []; c = candles
    if c[-5]["high"] < c[-4]["high"] and c[-3]["high"] < c[-4]["high"] and c[-1]["close"] < c[-3]["low"]:
        sinais.append({"padrao": "IDM Bearish", "dir": "VENDA",
            "nivel": c[-4]["high"], "prob_base": 73,
            "desc": f"Inducement varrido em {c[-4]['high']:.5f} — armadilha bearish confirmada"})
    if c[-5]["low"] > c[-4]["low"] and c[-3]["low"] > c[-4]["low"] and c[-1]["close"] > c[-3]["high"]:
        sinais.append({"padrao": "IDM Bullish", "dir": "COMPRA",
            "nivel": c[-4]["low"], "prob_base": 73,
            "desc": f"Inducement varrido em {c[-4]['low']:.5f} — armadilha bullish confirmada"})
    return sinais

def detectar_ifc(candles):
    if len(candles) < 15: return []
    sinais = []
    sh = max(v["high"] for v in candles[-15:-2])
    sl = min(v["low"]  for v in candles[-15:-2])
    sp = candles[-2]; at = candles[-1]; a = info(sp)
    if sp["high"] > sh and sp["close"] < sh and a["ss"] > a["corpo"]*1.5 and at["close"] < sp["low"]:
        sinais.append({"padrao": "IFC Bearish", "dir": "VENDA",
            "nivel": sh, "prob_base": 78,
            "desc": f"IFC varreu Session High {sh:.5f} — stops coletados, reversao confirmada"})
    if sp["low"] < sl and sp["close"] > sl and a["si"] > a["corpo"]*1.5 and at["close"] > sp["high"]:
        sinais.append({"padrao": "IFC Bullish", "dir": "COMPRA",
            "nivel": sl, "prob_base": 78,
            "desc": f"IFC varreu Session Low {sl:.5f} — stops coletados, reversao confirmada"})
    return sinais

def detectar_eqh_eql(candles, par):
    if len(candles) < 10: return []
    sinais = []; at = candles[-1]
    tol  = mov_minimo(par) * 5
    maxs = [v["high"] for v in candles[-20:-1]]
    mins = [v["low"]  for v in candles[-20:-1]]
    for i in range(len(maxs)-3):
        for j in range(i+2, len(maxs)):
            if abs(maxs[i] - maxs[j]) <= tol:
                nivel = (maxs[i] + maxs[j]) / 2
                if at["close"] > nivel:
                    sinais.append({"padrao": "EQH Sweep", "dir": "VENDA",
                        "nivel": nivel, "prob_base": 68,
                        "desc": f"Equal Highs varridos em {nivel:.5f} — liquidez retail coletada"})
                break
    for i in range(len(mins)-3):
        for j in range(i+2, len(mins)):
            if abs(mins[i] - mins[j]) <= tol:
                nivel = (mins[i] + mins[j]) / 2
                if at["close"] < nivel:
                    sinais.append({"padrao": "EQL Sweep", "dir": "COMPRA",
                        "nivel": nivel, "prob_base": 68,
                        "desc": f"Equal Lows varridos em {nivel:.5f} — liquidez retail coletada"})
                break
    return sinais

def detectar_pdh_pdl(candles, par):
    if len(candles) < 30: return []
    sinais = []; at = candles[-1]
    ant = candles[-48:-24]
    if not ant: return []
    pdh = max(v["high"] for v in ant)
    pdl = min(v["low"]  for v in ant)
    mn  = mov_minimo(par)
    mov = abs(at["close"] - at["open"])
    if at["close"] > pdh and mov >= mn:
        sinais.append({"padrao": "PDH Sweep", "dir": "VENDA",
            "nivel": pdh, "prob_base": 65,
            "desc": f"Varreu PDH {pdh:.5f} — liquidez diaria coletada"})
    if at["close"] < pdl and mov >= mn:
        sinais.append({"padrao": "PDL Sweep", "dir": "COMPRA",
            "nivel": pdl, "prob_base": 65,
            "desc": f"Varreu PDL {pdl:.5f} — liquidez diaria coletada"})
    return sinais

def detectar_ob(candles):
    if len(candles) < 6: return []
    sinais = []
    at  = candles[-1]; ob = candles[-2]; pre = candles[-3]
    med = sum(abs(v["close"]-v["open"]) for v in candles[-7:-1]) / 6
    cat = abs(at["close"] - at["open"])
    if cat < med * 0.8: return []
    if at["close"]>at["open"] and ob["close"]<ob["open"] and ob["low"]<pre["low"] and at["low"]>ob["high"]:
        sinais.append({"padrao": "Order Block", "sub": "BULLISH VALIDO", "dir": "COMPRA",
            "nivel": ob["low"], "prob_base": 72,
            "desc": f"OB Bullish com imbalance e sweep: {ob['low']:.5f}-{ob['high']:.5f}"})
    elif at["close"]<at["open"] and ob["close"]>ob["open"] and ob["high"]>pre["high"] and at["high"]<ob["low"]:
        sinais.append({"padrao": "Order Block", "sub": "BEARISH VALIDO", "dir": "VENDA",
            "nivel": ob["high"], "prob_base": 72,
            "desc": f"OB Bearish com imbalance e sweep: {ob['low']:.5f}-{ob['high']:.5f}"})
    elif at["close"]>at["open"] and ob["close"]<ob["open"] and cat>med*1.0:
        sinais.append({"padrao": "Order Block", "sub": "BULLISH", "dir": "COMPRA",
            "nivel": ob["low"], "prob_base": 62,
            "desc": f"OB Bullish: {ob['low']:.5f}-{ob['high']:.5f}"})
    elif at["close"]<at["open"] and ob["close"]>ob["open"] and cat>med*1.0:
        sinais.append({"padrao": "Order Block", "sub": "BEARISH", "dir": "VENDA",
            "nivel": ob["high"], "prob_base": 62,
            "desc": f"OB Bearish: {ob['low']:.5f}-{ob['high']:.5f}"})
    return sinais

def detectar_fvg(candles, par):
    if len(candles) < 4: return []
    sinais = []; mn = mov_minimo(par)
    v1,v2,v3 = candles[-3],candles[-2],candles[-1]
    if v3["low"] - v1["high"] > mn:
        sinais.append({"padrao": "FVG", "sub": "BULLISH", "dir": "COMPRA",
            "nivel": v1["high"], "prob_base": 63,
            "desc": f"Imbalance bullish {v1['high']:.5f}-{v3['low']:.5f} — preco tende a preencher"})
    if v1["low"] - v3["high"] > mn:
        sinais.append({"padrao": "FVG", "sub": "BEARISH", "dir": "VENDA",
            "nivel": v1["low"], "prob_base": 63,
            "desc": f"Imbalance bearish {v3['high']:.5f}-{v1['low']:.5f} — preco tende a preencher"})
    return sinais

def detectar_flip(candles):
    if len(candles) < 15: return []
    sinais = []; at = candles[-1]
    for i in range(5, 15):
        zh = candles[-i]["high"]; zl = candles[-i]["low"]
        if at["low"] <= zh and at["close"] > zh and candles[-3]["close"] > zh:
            sinais.append({"padrao": "FLiP S2D", "dir": "COMPRA",
                "nivel": zh, "prob_base": 70,
                "desc": f"Supply virou Demand em {zh:.5f} — reteste de zona rompida"}); break
        if at["high"] >= zl and at["close"] < zl and candles[-3]["close"] < zl:
            sinais.append({"padrao": "FLiP D2S", "dir": "VENDA",
                "nivel": zl, "prob_base": 70,
                "desc": f"Demand virou Supply em {zl:.5f} — reteste de zona rompida"}); break
    return sinais

def detectar_lg(candles, par):
    if len(candles) < 12: return []
    sinais = []
    maxr = max(v["high"] for v in candles[-12:-2])
    minr = min(v["low"]  for v in candles[-12:-2])
    sp = candles[-2]; at = candles[-1]; a = info(sp)
    co = max(a["corpo"], 0.00001)
    if sp["high"]>maxr and a["ss"]>co*CONFIG["lg_sombra_ratio"] and sp["close"]<maxr and at["close"]<sp["low"]:
        sinais.append({"padrao": "Liquidity Grab", "sub": "BEARISH", "dir": "VENDA",
            "nivel": maxr, "prob_base": 76,
            "desc": f"Stop hunt acima de {maxr:.5f} — rejeicao e queda confirmada"})
    if sp["low"]<minr and a["si"]>co*CONFIG["lg_sombra_ratio"] and sp["close"]>minr and at["close"]>sp["high"]:
        sinais.append({"padrao": "Liquidity Grab", "sub": "BULLISH", "dir": "COMPRA",
            "nivel": minr, "prob_base": 76,
            "desc": f"Stop hunt abaixo de {minr:.5f} — rejeicao e alta confirmada"})
    return sinais

# ============================================================
# CANDLES JAPONESES
# ============================================================
def detectar_candles(c):
    if len(c) < 4: return []
    padroes = []
    v1,v2,v3,v4 = c[-4],c[-3],c[-2],c[-1]
    a1,a2,a3,a4 = info(v1),info(v2),info(v3),info(v4)
    if a4["si"]>a4["corpo"]*2 and a4["cp"]<0.4 and a4["ss"]<a4["corpo"]:
        padroes.append({"nome":"Pin Bar Bullish","emoji":"📌🟢","dir":"COMPRA","bonus":10})
    if a4["ss"]>a4["corpo"]*2 and a4["cp"]<0.4 and a4["si"]<a4["corpo"]:
        padroes.append({"nome":"Pin Bar Bearish","emoji":"📌🔴","dir":"VENDA","bonus":10})
    if a3["baixa"] and a4["alta"] and v4["open"]<=v3["close"] and v4["close"]>=v3["open"]:
        padroes.append({"nome":"Engolfo Bullish","emoji":"🟢🔥","dir":"COMPRA","bonus":13})
    if a3["alta"] and a4["baixa"] and v4["open"]>=v3["close"] and v4["close"]<=v3["open"]:
        padroes.append({"nome":"Engolfo Bearish","emoji":"🔴🔥","dir":"VENDA","bonus":13})
    if a3["baixa"] and a4["alta"] and v4["open"]>v3["close"] and v4["close"]<v3["open"] and a4["corpo"]<a3["corpo"]*0.5:
        padroes.append({"nome":"Harami Bullish","emoji":"👶🟢","dir":"COMPRA","bonus":7})
    if a3["alta"] and a4["baixa"] and v4["open"]<v3["close"] and v4["close"]>v3["open"] and a4["corpo"]<a3["corpo"]*0.5:
        padroes.append({"nome":"Harami Bearish","emoji":"👶🔴","dir":"VENDA","bonus":7})
    if a2["baixa"] and a3["cp"]<0.1 and v3["high"]<v2["low"] and a4["alta"] and v4["open"]>v3["high"]:
        padroes.append({"nome":"Bebe Abandonado Bullish","emoji":"👶✨🟢","dir":"COMPRA","bonus":18})
    if a2["alta"] and a3["cp"]<0.1 and v3["low"]>v2["high"] and a4["baixa"] and v4["open"]<v3["low"]:
        padroes.append({"nome":"Bebe Abandonado Bearish","emoji":"👶✨🔴","dir":"VENDA","bonus":18})
    if a3["alta"] and a4["ss"]>a4["corpo"]*2 and a4["si"]<a4["corpo"]*0.5:
        padroes.append({"nome":"Estrela Cadente","emoji":"🌠🔴","dir":"VENDA","bonus":9})
    if a3["baixa"] and a4["si"]>a4["corpo"]*2 and a4["ss"]<a4["corpo"]*0.5:
        padroes.append({"nome":"Martelo","emoji":"🔨🟢","dir":"COMPRA","bonus":9})
    if a4["cp"] < 0.05:
        padroes.append({"nome":"Doji","emoji":"➕","dir":"NEUTRO","bonus":4})
    if a2["alta"] and a3["alta"] and a4["alta"] and v3["close"]>v2["close"] and v4["close"]>v3["close"] and a2["cp"]>0.6 and a3["cp"]>0.6 and a4["cp"]>0.6:
        padroes.append({"nome":"Tres Soldados Brancos","emoji":"⚔️🟢","dir":"COMPRA","bonus":14})
    if a2["baixa"] and a3["baixa"] and a4["baixa"] and v3["close"]<v2["close"] and v4["close"]<v3["close"] and a2["cp"]>0.6 and a3["cp"]>0.6 and a4["cp"]>0.6:
        padroes.append({"nome":"Tres Corvos Negros","emoji":"🦅🔴","dir":"VENDA","bonus":14})
    return padroes

# ============================================================
# MOTOR PRINCIPAL
# ============================================================
def analisar_par(par, tf):
    candles = buscar_candles(par, tf, CONFIG["velas_analisar"])
    if len(candles) < 20: return []

    at = candles[-1]
    zona, zona_pct = zona_premium_desconto(candles, at["close"])

    smc_list = (
        detectar_bos(candles, par)     +
        detectar_fbos(candles, par)    +
        detectar_choch(candles)        +
        detectar_idm(candles)          +
        detectar_ifc(candles)          +
        detectar_ob(candles)           +
        detectar_fvg(candles, par)     +
        detectar_flip(candles)         +
        detectar_lg(candles, par)      +
        detectar_eqh_eql(candles, par) +
        detectar_pdh_pdl(candles, par)
    )

    can_list      = detectar_candles(candles)
    sinais_finais = []

    for smc in smc_list:
        direcao = smc["dir"]
        prob    = smc["prob_base"]

        # Bonus/Penalidade zona Premium/Desconto
        if direcao == "COMPRA" and zona == "DESCONTO": prob += 8
        elif direcao == "VENDA" and zona == "PREMIUM":  prob += 8
        elif direcao == "COMPRA" and zona == "PREMIUM": prob -= 10
        elif direcao == "VENDA" and zona == "DESCONTO": prob -= 10

        # Bonus candles
        can_fav = [c for c in can_list if c["dir"] in [direcao, "NEUTRO"]]
        prob   += sum(c["bonus"] for c in can_fav)

        # Bonus multiplos SMC
        outros  = [s for s in smc_list if s["dir"] == direcao and s["padrao"] != smc["padrao"]]
        p
