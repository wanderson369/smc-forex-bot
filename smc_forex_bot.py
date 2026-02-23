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

import os, time, requests
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

PARES_CRYPTO = {
    "BTC/USD": "BTC/USD", "ETH/USD": "ETH/USD", "BNB/USD": "BNB/USD",
    "XRP/USD": "XRP/USD", "SOL/USD": "SOL/USD",
}

TODOS_PARES = {**PARES_FOREX, **PARES_CRYPTO}

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
    if at["close"] > maxima and mov >= mn:
        f = min(90, 62 + int(((at["close"] - maxima) / max(maxima, 0.0001)) * 8000))
        sinais.append({"padrao": "BOS", "sub": "ALTA", "dir": "COMPRA",
            "nivel": maxima, "prob_base": f,
            "desc": f"Rompimento bullish — fechamento acima de {maxima:.5f}"})
    if at["close"] < minima and mov >= mn:
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
    if cat < med * 1.2: return []
    if at["close"]>at["open"] and ob["close"]<ob["open"] and ob["low"]<pre["low"] and at["low"]>ob["high"]:
        sinais.append({"padrao": "Order Block", "sub": "BULLISH VALIDO", "dir": "COMPRA",
            "nivel": ob["low"], "prob_base": 72,
            "desc": f"OB Bullish com imbalance e sweep: {ob['low']:.5f}-{ob['high']:.5f}"})
    elif at["close"]<at["open"] and ob["close"]>ob["open"] and ob["high"]>pre["high"] and at["high"]<ob["low"]:
        sinais.append({"padrao": "Order Block", "sub": "BEARISH VALIDO", "dir": "VENDA",
            "nivel": ob["high"], "prob_base": 72,
            "desc": f"OB Bearish com imbalance e sweep: {ob['low']:.5f}-{ob['high']:.5f}"})
    elif at["close"]>at["open"] and ob["close"]<ob["open"] and cat>med*1.5:
        sinais.append({"padrao": "Order Block", "sub": "BULLISH", "dir": "COMPRA",
            "nivel": ob["low"], "prob_base": 62,
            "desc": f"OB Bullish: {ob['low']:.5f}-{ob['high']:.5f}"})
    elif at["close"]<at["open"] and ob["close"]>ob["open"] and cat>med*1.5:
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
        prob   += len(outros) * 5
        prob    = min(95, max(50, prob))

        if prob < CONFIG["prob_minima"]: continue

        sinais_finais.append({
            "par": par, "tf": tf, "direcao": direcao,
            "preco": at["close"], "horario": at["datetime"],
            "prob": prob, "zona": zona, "zona_pct": zona_pct,
            "smc_principal": smc, "outros_smc": outros, "candles": can_fav,
        })

    # Remove duplicatas — maior prob por direcao
    unicos = {}
    for s in sinais_finais:
        chave = f"{s['par']}_{s['tf']}_{s['direcao']}"
        if chave not in unicos or s["prob"] > unicos[chave]["prob"]:
            unicos[chave] = s

    return list(unicos.values())

# ============================================================
# FILTROS
# ============================================================
def passar_filtros(sinal):
    if CONFIG["filtro_pares"]   and sinal["par"] not in CONFIG["filtro_pares"]:   return False
    if CONFIG["meus_favoritos"] and sinal["par"] not in CONFIG["meus_favoritos"]: return False
    if CONFIG["filtro_direcao"] and sinal["direcao"] != CONFIG["filtro_direcao"]: return False
    if sinal["prob"] < CONFIG["filtro_prob"]: return False
    return True

# ============================================================
# FORMATACAO
# ============================================================
def barra(prob):
    f = int(prob / 10)
    return "█" * f + "░" * (10 - f)

def emoji_zona(zona):
    return {"PREMIUM": "🔴 PREMIUM", "DESCONTO": "🟢 DESCONTO", "EQUILIBRIO": "⚖️ EQUILIBRIO"}.get(zona, zona)

def formatar(s):
    emoji  = "🟢📈" if s["direcao"] == "COMPRA" else "🔴📉"
    prob   = s["prob"]
    conf   = "🔥 MUITO ALTO" if prob>=85 else "✅ ALTO" if prob>=70 else "⚡ MEDIO" if prob>=60 else "⚠️ BAIXO"
    smc    = s["smc_principal"]
    tf_n   = TF_NOMES.get(s["tf"], s["tf"])
    zona_t = emoji_zona(s["zona"])
    stop   = "Abaixo do OB/FVG" if s["direcao"] == "COMPRA" else "Acima do OB/FVG"

    outros_txt = ""
    if s["outros_smc"]:
        outros_txt = "\n🔹 <b>Confluencias SMC:</b>\n"
        outros_txt += "\n".join(f"  • {x['padrao']}: {x['desc'][:55]}" for x in s["outros_smc"][:3])

    can_txt = ""
    if s["candles"]:
        can_txt = "\n\n🕯 <b>Confirmacao de Candle:</b>\n"
        can_txt += "\n".join(f"  {x['emoji']} {x['nome']}" for x in s["candles"][:3])

    return (
        f"{emoji} <b>SINAL SMC — {s['par']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💱 <b>Par:</b>       {s['par']}\n"
        f"⏱ <b>Timeframe:</b> {tf_n}\n"
        f"🎯 <b>Direcao:</b>   {s['direcao']}\n"
        f"💰 <b>Preco:</b>     {s['preco']:.5f}\n"
        f"🗺 <b>Zona:</b>     {zona_t} ({s['zona_pct']:.0f}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Probabilidade: {prob}%</b>\n"
        f"{barra(prob)} {conf}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 <b>Padrao Principal:</b>\n"
        f"  🔹 {smc['padrao']} {smc.get('sub','')}\n"
        f"      {smc['desc']}\n"
        f"{outros_txt}{can_txt}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>Gestao de Risco:</b>\n"
        f"  Stop: {stop}\n"
        f"  RR alvo: 1:5 a 1:10\n"
        f"  Risco: max 1-2% do capital\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {converter_hora(s['horario'])} (Brasilia)\n"
        f"<i>Confirme sempre antes de entrar</i>"
    )

# ============================================================
# TELEGRAM
# ============================================================
def enviar(msg, chat_id=None):
    if TELEGRAM_TOKEN == "SEU_TOKEN_AQUI":
        print(f"[TG]\n{msg}\n"); return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id or TELEGRAM_CHAT_ID, "text": msg,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10)
    except Exception as e:
        print(f"Erro TG: {e}")

def buscar_updates():
    global ultimo_update_id
    if TELEGRAM_TOKEN == "SEU_TOKEN_AQUI": return []
    try:
        r    = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                            params={"offset": ultimo_update_id + 1, "timeout": 3}, timeout=8)
        upds = r.json().get("result", [])
        if upds: ultimo_update_id = upds[-1]["update_id"]
        return upds
    except: return []

# ============================================================
# COMANDOS
# ============================================================
def processar_comandos():
    for u in buscar_updates():
        msg   = u.get("message", {})
        texto = msg.get("text", "").strip()
        cid   = str(msg.get("chat", {}).get("id", ""))
        if not texto.startswith("/"): continue
        partes = texto.split(maxsplit=1)
        cmd    = partes[0].lower().split("@")[0]
        arg    = partes[1].strip().upper() if len(partes) > 1 else ""
        print(f"[CMD] {texto}")

        if cmd == "/start":
            enviar(
                "🤖 <b>SMC Forex Bot v4.1</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📊 <b>24 pares monitorados:</b>\n"
                "19 Forex + 5 Crypto\n\n"
                "📐 <b>Padroes SMC:</b>\n"
                "BOS · FBOS · CHoCH · IDM · SMT\n"
                "OB · FVG · FLiP · IFC · EQH/EQL\n"
                "PDH/PDL · Liquidity Grab\n\n"
                "🗺 Zonas Premium e Desconto\n"
                "🕯 Candles como complemento\n"
                "⏱ M1 · M5 · M15 · M30 · H1 · H4 · D1\n\n"
                "📋 Regra basica:\n"
                "🟢 + DESCONTO + 70% = COMPRA\n"
                "🔴 + PREMIUM  + 70% = VENDA\n\n"
                "Use /ajuda para ver todos os comandos.", cid)

        elif cmd == "/pares":
            enviar(
                "💱 <b>Pares Forex (19)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<b>Majors USD:</b>\n"
                "  EUR/USD · GBP/USD · USD/JPY\n"
                "  AUD/USD · USD/CHF · USD/CAD\n"
                "  NZD/USD\n\n"
                "<b>Cruzamentos:</b>\n"
                "  GBP/CAD · EUR/GBP · EUR/JPY\n"
                "  GBP/JPY · AUD/JPY · EUR/AUD\n"
                "  GBP/AUD · AUD/CHF · EUR/CHF · GBP/CHF\n\n"
                "<b>Metais:</b>\n"
                "  XAU/USD (Ouro) · XAG/USD (Prata)", cid)

        elif cmd == "/crypto":
            enviar(
                "🪙 <b>Pares Crypto (5)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "  • BTC/USD — Bitcoin\n"
                "  • ETH/USD — Ethereum\n"
                "  • BNB/USD — BNB\n"
                "  • XRP/USD — XRP\n"
                "  • SOL/USD — Solana\n\n"
                "Use /addfav BTC/USD para favoritar!", cid)

        elif cmd == "/tfs":
            tfs_ativos = ", ".join(TF_NOMES.get(t,t) for t in CONFIG["timeframes_ativos"])
            enviar(
                f"⏱ <b>Timeframes</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Ativos: {tfs_ativos}\n\n"
                f"<b>Disponiveis:</b>\n"
                f"  M1(1min) · M5(5min) · M15(15min)\n"
                f"  M30(30min) · H1(1h) · H4(4h) · D1(1day)\n\n"
                f"/addtf 1h   → ativar H1\n"
                f"/deltf 15min → desativar M15", cid)

        elif cmd == "/addtf":
            a = arg.lower()
            if a not in INTERVALOS:
                enviar("⚠️ Opcoes validas: 1min, 5min, 15min, 30min, 1h, 4h, 1day", cid)
            elif a in CONFIG["timeframes_ativos"]:
                enviar(f"⚠️ {TF_NOMES.get(a,a)} ja esta ativo.", cid)
            else:
                CONFIG["timeframes_ativos"].append(a)
                enviar(f"✅ {TF_NOMES.get(a,a)} ativado! TFs: {', '.join(TF_NOMES.get(t,t) for t in CONFIG['timeframes_ativos'])}", cid)

        elif cmd == "/deltf":
            a = arg.lower()
            if a in CONFIG["timeframes_ativos"]:
                CONFIG["timeframes_ativos"].remove(a)
                enviar(f"✅ {TF_NOMES.get(a,a)} removido.", cid)
            else:
                enviar(f"⚠️ {TF_NOMES.get(a,a)} nao encontrado nos ativos.", cid)

        elif cmd == "/favoritos":
            if not CONFIG["meus_favoritos"]:
                enviar("📭 Nenhum favorito ainda.\nUse /addfav EUR/USD para adicionar.", cid)
            else:
                lista = "\n".join(f"  ⭐ {p}" for p in CONFIG["meus_favoritos"])
                enviar(f"⭐ <b>Meus Favoritos ({len(CONFIG['meus_favoritos'])})</b>\n{lista}", cid)

        elif cmd == "/addfav":
            par = next((p for p in TODOS_PARES if
                        p.replace("/","") == arg.replace("/","") or p == arg), None)
            if not arg:
                enviar("⚠️ Use: /addfav EUR/USD ou /addfav EURUSD", cid)
            elif not par:
                enviar(f"⚠️ Par nao encontrado: {arg}\nUse /pares ou /crypto para ver a lista.", cid)
            elif par in CONFIG["meus_favoritos"]:
                enviar(f"⚠️ {par} ja esta nos favoritos.", cid)
            else:
                CONFIG["meus_favoritos"].append(par)
                enviar(f"⭐ {par} adicionado! Total: {len(CONFIG['meus_favoritos'])}", cid)

        elif cmd == "/delfav":
            par = next((p for p in TODOS_PARES if
                        p.replace("/","") == arg.replace("/","") or p == arg), None)
            if par and par in CONFIG["meus_favoritos"]:
                CONFIG["meus_favoritos"].remove(par)
                enviar(f"✅ {par} removido dos favoritos.", cid)
            else:
                enviar(f"⚠️ {arg} nao esta nos favoritos.", cid)

        elif cmd == "/filtrar":
            if not arg:
                enviar(
                    "⚙️ <b>Como usar /filtrar:</b>\n\n"
                    "/filtrar EUR/USD → so EUR/USD\n"
                    "/filtrar BTC/USD → so Bitcoin\n"
                    "/filtrar COMPRA  → so compras\n"
                    "/filtrar VENDA   → so vendas\n"
                    "/filtrar 70      → so prob >= 70%\n\n"
                    "Use /limpar para remover filtros.", cid)
            elif arg in ["COMPRA", "VENDA"]:
                CONFIG["filtro_direcao"] = arg
                enviar(f"✅ Filtro ativo: so sinais de <b>{arg}</b>", cid)
            elif arg.isdigit() and 50 <= int(arg) <= 95:
                CONFIG["filtro_prob"] = int(arg)
                enviar(f"✅ Filtro ativo: so prob >= <b>{arg}%</b>", cid)
            else:
                par = next((p for p in TODOS_PARES if
                            p.replace("/","") == arg.replace("/","") or p == arg), None)
                if par:
                    if par not in CONFIG["filtro_pares"]:
                        CONFIG["filtro_pares"].append(par)
                    enviar(f"✅ Filtro ativo: <b>{par}</b>", cid)
                else:
                    enviar("⚠️ Valor invalido. Use /filtrar sem argumento para ver exemplos.", cid)

        elif cmd == "/limpar":
            CONFIG["filtro_pares"]   = []
            CONFIG["filtro_direcao"] = ""
            CONFIG["filtro_prob"]    = CONFIG["prob_minima"]
            enviar("🧹 Filtros limpos! Recebendo todos os sinais.", cid)

        elif cmd == "/status":
            filtros = []
            if CONFIG["filtro_pares"]:   filtros.append(f"Pares: {', '.join(CONFIG['filtro_pares'])}")
            if CONFIG["filtro_direcao"]: filtros.append(f"Direcao: {CONFIG['filtro_direcao']}")
            if CONFIG["filtro_prob"] > CONFIG["prob_minima"]: filtros.append(f"Prob: >={CONFIG['filtro_prob']}%")
            tfs_n = ", ".join(TF_NOMES.get(t,t) for t in CONFIG["timeframes_ativos"])
            enviar(
                f"📊 <b>Status SMC Bot v4.1</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Estado    : {'⏸ Pausado' if CONFIG['pausado'] else '▶️ Ativo'}\n"
                f"Online    : {inicio}\n"
                f"Sinais    : {total_sinais}\n"
                f"Forex     : 19 pares\n"
                f"Crypto    : 5 pares\n"
                f"TFs       : {tfs_n}\n"
                f"Favoritos : {len(CONFIG['meus_favoritos'])}\n"
                f"Filtros   : {', '.join(filtros) if filtros else 'Nenhum'}\n"
                f"Hora      : {agora_brt()} (Brasilia)", cid)

        elif cmd == "/sinais":
            if not historico_sinais:
                enviar("📭 Nenhum sinal ainda.", cid)
            else:
                linhas = ["📜 <b>Ultimos Sinais</b>\n━━━━━━━━━━━━━━━━━━━━━━━"]
                for s in list(reversed(list(historico_sinais)))[:10]:
                    e   = "🟢" if s["direcao"] == "COMPRA" else "🔴"
                    tfn = TF_NOMES.get(s["tf"], s["tf"])
                    linhas.append(
                        f"{e} {s['par']} | {tfn} | {s['prob']}% | "
                        f"{s['smc_principal']['padrao']} | {s['zona']} | "
                        f"{converter_hora(s['horario'])}")
                enviar("\n".join(linhas), cid)

        elif cmd == "/pausar":
            CONFIG["pausado"] = True
            enviar("⏸ Alertas pausados. Use /retomar para reativar.", cid)

        elif cmd == "/retomar":
            CONFIG["pausado"] = False
            enviar("▶️ Alertas reativados!", cid)

        elif cmd == "/ajuda":
            enviar(
                "📖 <b>Todos os Comandos</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<b>Informacao:</b>\n"
                "/start       → boas vindas\n"
                "/status      → estado do bot\n"
                "/sinais      → ultimos 10 sinais\n"
                "/pares       → pares Forex\n"
                "/crypto      → pares Crypto\n"
                "/tfs         → timeframes ativos\n\n"
                "<b>Timeframes:</b>\n"
                "/addtf 1h    → ativar H1\n"
                "/deltf 15min → desativar M15\n\n"
                "<b>Favoritos:</b>\n"
                "/favoritos   → ver lista\n"
                "/addfav X    → adicionar par\n"
                "/delfav X    → remover par\n\n"
                "<b>Filtros:</b>\n"
                "/filtrar X   → filtrar sinais\n"
                "/limpar      → limpar filtros\n\n"
                "<b>Controle:</b>\n"
                "/pausar      → pausar alertas\n"
                "/retomar     → reativar alertas", cid)

# ============================================================
# LOOP PRINCIPAL
# ============================================================
def deve_verificar(par, tf):
    chave = f"{par}_{tf}"; agora = time.time()
    if agora - ultima_verificacao.get(chave, 0) >= INTERVALOS[tf]:
        ultima_verificacao[chave] = agora; return True
    return False

def main():
    global total_sinais
    print("=" * 60)
    print("  SMC FOREX BOT v4.1")
    print("  19 Forex + 5 Crypto | M1 ate D1")
    print("  BOS/FBOS/CHoCH/IDM/OB/FVG/FLiP/IFC/EQH/LG")
    print("  Zonas Premium e Desconto | Horario Brasilia")
    print("=" * 60)

    enviar(
        "🤖 <b>SMC Forex Bot v4.1 Online!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ 19 pares Forex (+ NZD/USD e GBP/CAD)\n"
        "✅ 5 pares Crypto (BTC/ETH/BNB/XRP/SOL)\n"
        "✅ Timeframes M1 ate D1\n"
        "✅ Zonas Premium e Desconto\n"
        "✅ Horario de Brasilia\n\n"
        "Regra:\n"
        "🟢 COMPRA + DESCONTO + 70% = entrar\n"
        "🔴 VENDA  + PREMIUM  + 70% = entrar\n\n"
        "Use /ajuda para ver todos os comandos.")

    while True:
        try:
            processar_comandos()
        except Exception as e:
            print(f"Erro cmd: {e}")

        if not CONFIG["pausado"]:
            for par in CONFIG["pares_ativos"]:
                for tf in CONFIG["timeframes_ativos"]:
                    if not deve_verificar(par, tf): continue
                    tf_n = TF_NOMES.get(tf, tf)
                    print(f"[{agora_brt()}] Analisando {par} {tf_n}")
                    try:
                        sinais = analisar_par(par, tf)
                    except Exception as e:
                        print(f"Erro analise {par}: {e}"); continue

                    for s in sinais:
                        if not passar_filtros(s): continue
                        chave = f"{s['par']}_{s['tf']}_{s['direcao']}_{s['horario']}"
                        if chave in sinais_enviados: continue
                        sinais_enviados[chave] = True
                        total_sinais += 1
                        historico_sinais.append(s)
                        tf_n = TF_NOMES.get(s["tf"], s["tf"])
                        print(f"  SINAL: {s['direcao']} {s['par']} {tf_n} "
                              f"{s['prob']}% | {s['smc_principal']['padrao']} | {s['zona']}")
                        enviar(formatar(s))
                    time.sleep(2)

        time.sleep(10)

if __name__ == "__main__":
    main()
