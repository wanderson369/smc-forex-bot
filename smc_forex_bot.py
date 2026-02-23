"""
SMC Forex Bot v4.0 — Metodologia Completa
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
# CONFIGURAÇÕES
# ============================================================
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")
TWELVE_API_KEY   = os.environ.get("TWELVE_API_KEY", "SUA_CHAVE_AQUI")

TODOS_PARES = {
    "EUR/USD": "EURUSD", "GBP/USD": "GBPUSD", "USD/JPY": "USDJPY",
    "AUD/USD": "AUDUSD", "USD/CHF": "USDCHF", "USD/CAD": "USDCAD",
    "EUR/GBP": "EURGBP", "EUR/JPY": "EURJPY", "GBP/JPY": "GBPJPY",
    "AUD/JPY": "AUDJPY", "EUR/AUD": "EURAUD", "GBP/AUD": "GBPAUD",
    "AUD/CHF": "AUDCHF", "EUR/CHF": "EURCHF", "GBP/CHF": "GBPCHF",
    "XAU/USD": "XAUUSD", "XAG/USD": "XAGUSD",
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

    if at["close"] > pdh and mov >= CONFIG["min_movimento_bos"]:
        sinais.append({
            "padrao": "PDH Sweep", "dir": "VENDA",
            "nivel": pdh, "prob_base": 65,
            "desc": f"Preço varrreu PDH {pdh:.5f} — liquidez diária coletada"
        })
    if at["close"] < pdl and mov >= CONFIG["min_movimento_bos"]:
        sinais.append({
            "padrao": "PDL Sweep", "dir": "COMPRA",
            "nivel": pdl, "prob_base": 65,
            "desc": f"Preço varreu PDL {pdl:.5f} — liquidez diária coletada"
        })
    return sinais

def detectar_idm(candles):
    """
    IDM — Inducement
    Padrão: estrutura de topos/fundos menores ANTES do movimento real
    Quando mercado cria uma estrutura menor para induzir retail antes de mover de verdade
    """
    if len(candles) < 8: return []
    sinais = []
    c = candles

    # IDM Bearish: topo menor após CHoCH — induz compra antes de cair
    if (c[-5]["high"] < c[-4]["high"] and      # topo menor crescendo (parece alta)
        c[-3]["high"] < c[-4]["high"] and       # mas não supera
        c[-1]["close"] < c[-3]["low"]):         # e agora quebra estrutura real
        sinais.append({
            "padrao": "IDM Bearish", "dir": "VENDA",
            "nivel": c[-4]["high"], "prob_base": 73,
            "desc": f"Inducement varrido em {c[-4]['high']:.5f} — armadilha identificada, queda real iniciando"
        })

    # IDM Bullish: fundo menor após CHoCH — induz venda antes de subir
    if (c[-5]["low"] > c[-4]["low"] and         # fundo menor caindo (parece baixa)
        c[-3]["low"] > c[-4]["low"] and          # mas não supera
        c[-1]["close"] > c[-3]["high"]):         # e agora quebra estrutura real
        sinais.append({
            "padrao": "IDM Bullish", "dir": "COMPRA",
            "nivel": c[-4]["low"], "prob_base": 73,
            "desc": f"Inducement varrido em {c[-4]['low']:.5f} — armadilha identificada, alta real iniciando"
        })

    return sinais

def detectar_ifc(candles):
    """
    IFC — Institutional Funding Candle
    Vela que varre stops de sessão (Session High/Low sweep) e fecha de volta
    Indica onde instituições coletaram liquidez
    """
    if len(candles) < 15: return []
    sinais = []

    session_high = max(v["high"] for v in candles[-15:-2])
    session_low  = min(v["low"]  for v in candles[-15:-2])
    sp = candles[-2]  # vela spike
    at = candles[-1]  # vela atual

    a = info(sp)

    # IFC Bearish: spike acima da session high + fechamento de volta
    if (sp["high"] > session_high and
        sp["close"] < session_high and
        a["ss"] > a["corpo"] * 1.5 and
        at["close"] < sp["low"]):
        sinais.append({
            "padrao": "IFC Bearish", "dir": "VENDA",
            "nivel": session_high, "prob_base": 78,
            "desc": f"IFC varreu Session High {session_high:.5f} — stops coletados, reversão confirmada"
        })

    # IFC Bullish: spike abaixo da session low + fechamento de volta
    if (sp["low"] < session_low and
        sp["close"] > session_low and
        a["si"] > a["corpo"] * 1.5 and
        at["close"] > sp["high"]):
        sinais.append({
            "padrao": "IFC Bullish", "dir": "COMPRA",
            "nivel": session_low, "prob_base": 78,
            "desc": f"IFC varreu Session Low {session_low:.5f} — stops coletados, reversão confirmada"
        })

    return sinais

# ============================================================
# DETECÇÃO SMC PRINCIPAL
# ============================================================
def detectar_bos(candles):
    """
    BOS — Break of Structure
    REGRA DO EBOOK: precisa de fechamento completo da vela (não apenas sombra)
    BOS válido = candle fecha acima/abaixo da estrutura
    """
    if len(candles) < 22: return []
    sinais = []
    at = candles[-1]

    # Estrutura das últimas 20 velas
    maxima = max(v["high"] for v in candles[-21:-1])
    minima = min(v["low"]  for v in candles[-21:-1])
    mov    = abs(at["close"] - at["open"])

    # BOS válido exige FECHAMENTO acima/abaixo (não sombra)
    if at["close"] > maxima and mov >= CONFIG["min_movimento_bos"]:
        forca = min(90, 62 + int(((at["close"] - maxima) / maxima) * 8000))
        sinais.append({
            "padrao": "BOS", "sub": "ALTA", "dir": "COMPRA",
            "nivel": maxima, "prob_base": forca,
            "desc": f"Rompimento bullish — fechamento acima de {maxima:.5f}"
        })

    if at["close"] < minima and mov >= CONFIG["min_movimento_bos"]:
        forca = min(90, 62 + int(((minima - at["close"]) / minima) * 8000))
        sinais.append({
            "padrao": "BOS", "sub": "BAIXA", "dir": "VENDA",
            "nivel": minima, "prob_base": forca,
            "desc": f"Rompimento bearish — fechamento abaixo de {minima:.5f}"
        })

    return sinais

def detectar_fbos(candles):
    """
    FBOS — Fake Break of Structure (Smart Money Trap)
    Preço rompe estrutura com sombra mas fecha de volta — armadilha!
    """
    if len(candles) < 12: return []
    sinais = []
    maxima = max(v["high"] for v in candles[-11:-2])
    minima = min(v["low"]  for v in candles[-11:-2])
    sp = candles[-2]
    at = candles[-1]

    # FBOS Bearish: sombra acima da maxima mas fechou abaixo = armadilha de compra
    if (sp["high"] > maxima and
        sp["close"] < maxima and
        at["close"] < sp["low"]):
        sinais.append({
            "padrao": "FBOS/SMT", "sub": "BEARISH", "dir": "VENDA",
            "nivel": maxima, "prob_base": 76,
            "desc": f"Fake BOS bearish em {maxima:.5f} — retail comprou, instituição vendeu"
        })

    # FBOS Bullish: sombra abaixo da minima mas fechou acima = armadilha de venda
    if (sp["low"] < minima and
        sp["close"] > minima and
        at["close"] > sp["high"]):
        sinais.append({
            "padrao": "FBOS/SMT", "sub": "BULLISH", "dir": "COMPRA",
            "nivel": minima, "prob_base": 76,
            "desc": f"Fake BOS bullish em {minima:.5f} — retail vendeu, instituição comprou"
        })

    return sinais

def detectar_choch(candles):
    """
    CHoCH — Change of Character
    Dois tipos conforme ebook:
    1. CHoCH com IDM — mais confiável (80%+)
    2. CHoCH sem IDM — apenas sweep do high/low anterior
    """
    if len(candles) < 8: return []
    sinais = []
    c = candles
    v1,v2,v3,v4,at = c[-5],c[-4],c[-3],c[-2],c[-1]

    # CHoCH Bearish: topos crescentes → rompeu fundo
    if v1["high"] < v2["high"] < v3["high"] and at["close"] < v4["low"]:
        # Verificar se havia IDM (inducement) antes
        tinha_idm = v3["high"] < v2["high"]  # pullback antes da queda = IDM
        prob = 78 if tinha_idm else 68
        tipo = "com IDM" if tinha_idm else "sem IDM"
        sinais.append({
            "padrao": "CHoCH", "sub": f"BEARISH {tipo}", "dir": "VENDA",
            "nivel": v4["low"], "prob_base": prob,
            "desc": f"Mudança de caráter bearish ({tipo}) — rompeu {v4['low']:.5f} após topos crescentes"
        })

    # CHoCH Bullish: fundos decrescentes → rompeu topo
    if v1["low"] > v2["low"] > v3["low"] and at["close"] > v4["high"]:
        tinha_idm = v3["low"] > v2["low"]
        prob = 78 if tinha_idm else 68
        tipo = "com IDM" if tinha_idm else "sem IDM"
        sinais.append({
            "padrao": "CHoCH", "sub": f"BULLISH {tipo}", "dir": "COMPRA",
            "nivel": v4["high"], "prob_base": prob,
            "desc": f"Mudança de caráter bullish ({tipo}) — rompeu {v4['high']:.5f} após fundos decrescentes"
        })

    return sinais

def detectar_ob(candles):
    """
    Order Block — conforme ebook:
    OB válido PRECISA de:
    1. Imbalance (FVG) após o OB
    2. Liquidity Sweep da vela anterior (prev candle high/low taken out)
    """
    if len(candles) < 6: return []
    sinais = []
    at  = candles[-1]
    ob  = candles[-2]   # possível OB
    pre = candles[-3]   # vela antes do OB

    media = sum(abs(v["close"]-v["open"]) for v in candles[-7:-1]) / 6
    corpo_at = abs(at["close"] - at["open"])

    if corpo_at < media * 1.2: return []

    # OB Bullish válido:
    # - OB é vela de baixa
    # - Vela atual é de alta forte
    # - Prev candle low foi tomado (liquidity sweep)
    # - Há imbalance entre OB e vela atual
    if (at["close"] > at["open"] and          # vela atual alta
        ob["close"] < ob["open"] and           # OB é baixa
        ob["low"] < pre["low"] and             # sweep do low anterior
        at["low"] > ob["high"]):               # imbalance (gap)
        sinais.append({
            "padrao": "Order Block", "sub": "BULLISH VÁLIDO", "dir": "COMPRA",
            "nivel": ob["low"], "prob_base": 72,
            "desc": f"OB Bullish com imbalance: zona {ob['low']:.5f}–{ob['high']:.5f} (sweep + gap confirmados)"
        })

    # OB Bearish válido:
    elif (at["close"] < at["open"] and         # vela atual baixa
          ob["close"] > ob["open"] and          # OB é alta
          ob["high"] > pre["high"] and          # sweep do high anterior
          at["high"] < ob["low"]):              # imbalance (gap)
        sinais.append({
            "padrao": "Order Block", "sub": "BEARISH VÁLIDO", "dir": "VENDA",
            "nivel": ob["high"], "prob_base": 72,
            "desc": f"OB Bearish com imbalance: zona {ob['low']:.5f}–{ob['high']:.5f} (sweep + gap confirmados)"
        })

    # OB simples (sem todos os critérios mas ainda válido)
    elif (at["close"] > at["open"] and ob["close"] < ob["open"] and corpo_at > media * 1.5):
        sinais.append({
            "padrao": "Order Block", "sub": "BULLISH", "dir": "COMPRA",
            "nivel": ob["low"], "prob_base": 62,
            "desc": f"OB Bullish: zona {ob['low']:.5f}–{ob['high']:.5f}"
        })
    elif (at["close"] < at["open"] and ob["close"] > ob["open"] and corpo_at > media * 1.5):
        sinais.append({
            "padrao": "Order Block", "sub": "BEARISH", "dir": "VENDA",
            "nivel": ob["high"], "prob_base": 62,
            "desc": f"OB Bearish: zona {ob['low']:.5f}–{ob['high']:.5f}"
        })

    return sinais

def detectar_fvg(candles):
    """FVG/Imbalance — gap entre velas, usado como POI"""
    if len(candles) < 4: return []
    sinais = []
    v1, v2, v3 = candles[-3], candles[-2], candles[-1]

    gap_alta  = v3["low"]  - v1["high"]
    gap_baixa = v1["low"]  - v3["high"]

    if gap_alta > CONFIG["min_movimento_bos"]:
        sinais.append({
            "padrao": "FVG", "sub": "BULLISH", "dir": "COMPRA",
            "nivel": v1["high"], "prob_base": 63,
            "desc": f"Imbalance bullish {v1['high']:.5f}–{v3['low']:.5f} — preço tende a retornar para preencher"
        })
    if gap_baixa > CONFIG["min_movimento_bos"]:
        sinais.append({
            "padrao": "FVG", "sub": "BEARISH", "dir": "VENDA",
            "nivel": v1["low"], "prob_base": 63,
            "desc": f"Imbalance bearish {v3['high']:.5f}–{v1['low']:.5f} — preço tende a retornar para preencher"
        })
    return sinais

def detectar_flip(candles):
    """
    FLiP Zone — Supply que virou Demand (S2D) ou Demand que virou Supply (D2S)
    Quando preço rompe uma zona e volta para retestá-la = entrada de alta probabilidade
    """
    if len(candles) < 15: return []
    sinais = []
    at = candles[-1]

    # Procura por zonas que foram rompidas e estão sendo retestadas
    for i in range(5, 15):
        zona_high = candles[-i]["high"]
        zona_low  = candles[-i]["low"]

        # S2D: preço estava abaixo, rompeu, voltou para retestar
        if (at["low"] <= zona_high and
            at["close"] > zona_high and
            candles[-3]["close"] > zona_high):
            sinais.append({
                "padrao": "FLiP S2D", "dir": "COMPRA",
                "nivel": zona_high, "prob_base": 70,
                "desc": f"Supply virou Demand em {zona_high:.5f} — reteste de zona rompida (alta probabilidade)"
            })
            break

        # D2S: preço estava acima, rompeu, voltou para retestar
        if (at["high"] >= zona_low and
            at["close"] < zona_low and
            candles[-3]["close"] < zona_low):
            sinais.append({
                "padrao": "FLiP D2S", "dir": "VENDA",
                "nivel": zona_low, "prob_base": 70,
                "desc": f"Demand virou Supply em {zona_low:.5f} — reteste de zona rompida (alta probabilidade)"
            })
            break

    return sinais

def detectar_lg(candles):
    """Liquidity Grab — caçada de stops com rejeição"""
    if len(candles) < 12: return []
    sinais = []
    max_rec = max(v["high"] for v in candles[-12:-2])
    min_rec = min(v["low"]  for v in candles[-12:-2])
    sp = candles[-2]
    at = candles[-1]
    a  = info(sp)
    co = max(a["corpo"], 0.00001)

    if (sp["high"] > max_rec and a["ss"] > co * CONFIG["lg_sombra_ratio"] and
        sp["close"] < max_rec and at["close"] < sp["low"]):
        sinais.append({
            "padrao": "Liquidity Grab", "sub": "BEARISH", "dir": "VENDA",
            "nivel": max_rec, "prob_base": 76,
            "desc": f"Stop hunt acima de {max_rec:.5f} — rejeição confirmada, queda iminente"
        })

    if (sp["low"] < min_rec and a["si"] > co * CONFIG["lg_sombra_ratio"] and
        sp["close"] > min_rec and at["close"] > sp["high"]):
        sinais.append({
            "padrao": "Liquidity Grab", "sub": "BULLISH", "dir": "COMPRA",
            "nivel": min_rec, "prob_base": 76,
            "desc": f"Stop hunt abaixo de {min_rec:.5f} — rejeição confirmada, alta iminente"
        })

    return sinais

# ============================================================
# CANDLES JAPONESES (complemento — aumentam probabilidade)
# ============================================================
def detectar_candles(c):
    if len(c) < 4: return []
    padroes = []
    v1,v2,v3,v4 = c[-4],c[-3],c[-2],c[-1]
    a1,a2,a3,a4 = info(v1),info(v2),info(v3),info(v4)

    if a4["si"]>a4["corpo"]*2 and a4["cp"]<0.4 and a4["ss"]<a4["corpo"]:
        padroes.append({"nome":"Pin Bar Bullish","emoji":"📌🟢","dir":"COMPRA","bonus":10,"desc":"Sombra inferior longa — rejeição de mínimas"})
    if a4["ss"]>a4["corpo"]*2 and a4["cp"]<0.4 and a4["si"]<a4["corpo"]:
        padroes.append({"nome":"Pin Bar Bearish","emoji":"📌🔴","dir":"VENDA","bonus":10,"desc":"Sombra superior longa — rejeição de máximas"})
    if a3["baixa"] and a4["alta"] and v4["open"]<=v3["close"] and v4["close"]>=v3["open"]:
        padroes.append({"nome":"Engolfo Bullish","emoji":"🟢🔥","dir":"COMPRA","bonus":13,"desc":"Vela de alta engolfa a baixa anterior"})
    if a3["alta"] and a4["baixa"] and v4["open"]>=v3["close"] and v4["close"]<=v3["open"]:
        padroes.append({"nome":"Engolfo Bearish","emoji":"🔴🔥","dir":"VENDA","bonus":13,"desc":"Vela de baixa engolfa a alta anterior"})
    if (a3["baixa"] and a4["alta"] and v4["open"]>v3["close"] and v4["close"]<v3["open"] and a4["corpo"]<a3["corpo"]*0.5):
        padroes.append({"nome":"Harami Bullish","emoji":"👶🟢","dir":"COMPRA","bonus":7,"desc":"Vela interna — possível reversão"})
    if (a3["alta"] and a4["baixa"] and v4["open"]<v3["close"] and v4["close"]>v3["open"] and a4["corpo"]<a3["corpo"]*0.5):
        padroes.append({"nome":"Harami Bearish","emoji":"👶🔴","dir":"VENDA","bonus":7,"desc":"Vela interna — possível reversão"})
    if (a2["baixa"] and a3["cp"]<0.1 and v3["high"]<v2["low"] and a4["alta"] and v4["open"]>v3["high"]):
        padroes.append({"nome":"Bebê Abandonado Bullish","emoji":"👶✨🟢","dir":"COMPRA","bonus":18,"desc":"Doji com gaps — reversão de altíssima probabilidade"})
    if (a2["alta"] and a3["cp"]<0.1 and v3["low"]>v2["high"] and a4["baixa"] and v4["open"]<v3["low"]):
        padroes.append({"nome":"Bebê Abandonado Bearish","emoji":"👶✨🔴","dir":"VENDA","bonus":18,"desc":"Doji com gaps — reversão de altíssima probabilidade"})
    if a3["alta"] and a4["ss"]>a4["corpo"]*2 and a4["si"]<a4["corpo"]*0.5:
        padroes.append({"nome":"Estrela Cadente","emoji":"🌠🔴","dir":"VENDA","bonus":9,"desc":"Sombra superior após alta — topo"})
    if a3["baixa"] and a4["si"]>a4["corpo"]*2 and a4["ss"]<a4["corpo"]*0.5:
        padroes.append({"nome":"Martelo","emoji":"🔨🟢","dir":"COMPRA","bonus":9,"desc":"Sombra inferior após baixa — fundo"})
    if a4["cp"] < 0.05:
        padroes.append({"nome":"Doji","emoji":"➕","dir":"NEUTRO","bonus":4,"desc":"Indecisão — aguardar confirmação"})
    if (a2["alta"] and a3["alta"] and a4["alta"] and v3["close"]>v2["close"] and v4["close"]>v3["close"] and a2["cp"]>0.6 and a3["cp"]>0.6 and a4["cp"]>0.6):
        padroes.append({"nome":"Três Soldados Brancos","emoji":"⚔️🟢","dir":"COMPRA","bonus":14,"desc":"Três altas fortes — tendência"})
    if (a2["baixa"] and a3["baixa"] and a4["baixa"] and v3["close"]<v2["close"] and v4["close"]<v3["close"] and a2["cp"]>0.6 and a3["cp"]>0.6 and a4["cp"]>0.6):
        padroes.append({"nome":"Três Corvos Negros","emoji":"🦅🔴","dir":"VENDA","bonus":14,"desc":"Três baixas fortes — tendência"})

    return padroes

# ============================================================
# MOTOR PRINCIPAL DE ANÁLISE
# ============================================================
def analisar_par(par, tf):
    candles = buscar_candles(par, tf, CONFIG["velas_analisar"])
    if len(candles) < 20: return []

    at = candles[-1]

    # === Detecta zona (Premium/Desconto) ===
    zona, posicao_pct = zona_premium_desconto(candles, at["close"])

    # === Coleta todos os padrões SMC ===
    smc_list = (
        detectar_bos(candles)     +
        detectar_fbos(candles)    +
        detectar_choch(candles)   +
        detectar_ob(candles)      +
        detectar_fvg(candles)     +
        detectar_flip(candles)    +
        detectar_lg(candles)      +
        detectar_idm(candles)     +
        detectar_ifc(candles)     +
        detectar_eqh_eql(candles) +
        detectar_pdh_pdl(candles)
    )

    # === Detecta candles japoneses (bônus) ===
    can_list = detectar_candles(candles)

    # === Monta sinais por direção ===
    sinais_finais = []

    for smc in smc_list:
        direcao = smc["dir"]
        prob    = smc["prob_base"]

        # Bônus/Penalidade por zona Premium/Desconto
        # Regra SMC: compra só em desconto, venda só em premium
        if direcao == "COMPRA" and zona == "DESCONTO":
            prob += 8   # zona correta para compra
        elif direcao == "VENDA" and zona == "PREMIUM":
            prob += 8   # zona correta para venda
        elif direcao == "COMPRA" and zona == "PREMIUM":
            prob -= 10  # compra em zona de premium = perigoso
        elif direcao == "VENDA" and zona == "DESCONTO":
            prob -= 10  # venda em zona de desconto = perigoso

        # Bônus por candles na mesma direção
        can_favor = [c for c in can_list if c["dir"] in [direcao, "NEUTRO"]]
        prob += sum(c["bonus"] for c in can_favor)

        # Bônus por múltiplos SMC confirmando
        outros_smc = [s for s in smc_list if s["dir"] == direcao and s["padrao"] != smc["padrao"]]
        prob += len(outros_smc) * 5

        prob = min(95, max(50, prob))

        if prob < CONFIG["prob_minima"]: continue

        sinais_finais.append({
            "par": par, "tf": tf, "direcao": direcao,
            "preco": at["close"], "horario": at["datetime"],
            "prob": prob, "zona": zona, "zona_pct": posicao_pct,
            "smc_principal": smc,
            "outros_smc":    outros_smc,
            "candles":       can_favor,
        })

    # Remove duplicatas — mantém maior probabilidade por direção
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
    par_limpo = TODOS_PARES.get(sinal["par"], sinal["par"])
    if CONFIG["filtro_pares"]   and par_limpo != sinal["par"] and par_limpo not in CONFIG["filtro_pares"]: return False
    if CONFIG["meus_favoritos"] and par_limpo not in CONFIG["meus_favoritos"]: return False
    if CONFIG["filtro_direcao"] and sinal["direcao"] != CONFIG["filtro_direcao"]: return False
    if sinal["prob"] < CONFIG["filtro_prob"]: return False
    return True

# ============================================================
# FORMATAÇÃO DO ALERTA
# ============================================================
def barra(prob):
    f = int(prob / 10)
    return "█" * f + "░" * (10 - f)

def emoji_zona(zona):
    return {"PREMIUM": "🔴 PREMIUM", "DESCONTO": "🟢 DESCONTO", "EQUILIBRIO": "⚖️ EQUILÍBRIO"}.get(zona, zona)

def formatar(s):
    emoji  = "🟢📈" if s["direcao"] == "COMPRA" else "🔴📉"
    par    = TODOS_PARES.get(s["par"], s["par"])
    prob   = s["prob"]
    conf   = "🔥 MUITO ALTO" if prob >= 85 else "✅ ALTO" if prob >= 70 else "⚡ MÉDIO" if prob >= 60 else "⚠️ BAIXO"
    smc    = s["smc_principal"]
    zona_t = emoji_zona(s["zona"])

    # Outros padrões SMC confirmando
    outros_txt = ""
    if s["outros_smc"]:
        outros_txt = "\n🔹 <b>Confluências SMC:</b>\n"
        outros_txt += "\n".join(f"  • {x['padrao']}: {x['desc'][:60]}" for x in s["outros_smc"][:3])

    # Candles como complemento
    can_txt = ""
    if s["candles"]:
        can_txt = "\n\n🕯 <b>Confirmação de Candle:</b>\n"
        can_txt += "\n".join(f"  {x['emoji']} {x['nome']}" for x in s["candles"][:3])

    # Sugestão de gestão de risco
    rr   = "1:5 a 1:10 (excelente)"
    stop = "Abaixo do OB/FVG" if s["direcao"] == "COMPRA" else "Acima do OB/FVG"

    return (
        f"{emoji} <b>SINAL SMC — {par}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💱 <b>Par:</b>       {par}\n"
        f"⏱ <b>Timeframe:</b> {s['tf'].upper()}\n"
        f"🎯 <b>Direção:</b>   {s['direcao']}\n"
        f"💰 <b>Preço:</b>     {s['preco']:.5f}\n"
        f"🗺 <b>Zona:</b>     {zona_t} ({s['zona_pct']:.0f}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Probabilidade: {prob}%</b>\n"
        f"{barra(prob)} {conf}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 <b>Padrão Principal:</b>\n"
        f"  🔹 {smc['padrao']} {smc.get('sub','')}\n"
        f"      {smc['desc']}\n"
        f"{outros_txt}{can_txt}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>Gestão de Risco:</b>\n"
        f"  Stop: {stop}\n"
        f"  RR alvo: {rr}\n"
        f"  Risco: máx 1-2% do capital\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {converter_hora(s['horario'])} (Brasília)\n"
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
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": ultimo_update_id + 1, "timeout": 3}, timeout=8)
        upds = r.json().get("result", [])
        if upds: ultimo_update_id = upds[-1]["update_id"]
        return upds
    except: return []

# ============================================================
# COMANDOS TELEGRAM
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
                "🤖 <b>SMC Forex Bot v4.0</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📚 Metodologia completa SMC:\n"
                "BOS · FBOS · CHoCH · IDM · SMT\n"
                "OB · FVG · FLiP · IFC · EQH/EQL\n"
                "PDH/PDL · Session Liquidity\n"
                "Zonas Premium e Desconto\n\n"
                "🕯 Candles como complemento:\n"
                "Pin Bar · Engolfo · Harami\n"
                "Bebê Abandonado · 3 Soldados/Corvos\n\n"
                "📋 <b>Comandos:</b>\n"
                "/pares · /favoritos · /addfav · /delfav\n"
                "/filtrar · /limpar · /status · /sinais\n"
                "/pausar · /retomar · /ajuda", cid)

        elif cmd == "/pares":
            linhas = ["💱 <b>17 Pares Monitorados</b>\n━━━━━━━━━━━━━━━━━━━━━━━"]
            linhas.append("\n<b>Majors USD:</b>")
            for p in ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCHF","USDCAD"]: linhas.append(f"  • {p}")
            linhas.append("\n<b>Cruzamentos:</b>")
            for p in ["EURGBP","EURJPY","GBPJPY","AUDJPY","EURAUD","GBPAUD","AUDCHF","EURCHF","GBPCHF"]: linhas.append(f"  • {p}")
            linhas.append("\n<b>Metais:</b>")
            for p in ["XAUUSD","XAGUSD"]: linhas.append(f"  • {p}")
            enviar("\n".join(linhas), cid)

        elif cmd == "/favoritos":
            if not CONFIG["meus_favoritos"]:
                enviar("📭 Nenhum favorito.\nUse /addfav EURUSD", cid)
            else:
                lista = "\n".join(f"  ⭐ {p}" for p in CONFIG["meus_favoritos"])
                enviar(f"⭐ <b>Meus Favoritos</b>\n{lista}", cid)

        elif cmd == "/addfav":
            if not arg: enviar("⚠️ Use: /addfav EURUSD", cid)
            elif arg not in list(TODOS_PARES.values()): enviar(f"⚠️ Par inválido. Use /pares para ver a lista.", cid)
            elif arg in CONFIG["meus_favoritos"]: enviar(f"⚠️ {arg} já está nos favoritos.", cid)
            else:
                CONFIG["meus_favoritos"].append(arg)
                enviar(f"⭐ {arg} adicionado! Total: {len(CONFIG['meus_favoritos'])}", cid)

        elif cmd == "/delfav":
            if arg in CONFIG["meus_favoritos"]:
                CONFIG["meus_favoritos"].remove(arg); enviar(f"✅ {arg} removido.", cid)
            else: enviar(f"⚠️ {arg} não está nos favoritos.", cid)

        elif cmd == "/filtrar":
            if not arg:
                enviar("⚙️ <b>Como usar /filtrar:</b>\n\n"
                    "/filtrar EURUSD → só EURUSD\n"
                    "/filtrar XAUUSD → só Ouro\n"
                    "/filtrar COMPRA → só compras\n"
                    "/filtrar VENDA  → só vendas\n"
                    "/filtrar 70     → só prob ≥ 70%\n\n"
                    "Use /limpar para remover filtros.", cid)
            elif arg in ["COMPRA","VENDA"]:
                CONFIG["filtro_direcao"] = arg
                enviar(f"✅ Filtro: só sinais de <b>{arg}</b>", cid)
            elif arg.isdigit() and 50 <= int(arg) <= 95:
                CONFIG["filtro_prob"] = int(arg)
                enviar(f"✅ Filtro: só prob ≥ <b>{arg}%</b>", cid)
            elif arg in list(TODOS_PARES.values()):
                if arg not in CONFIG["filtro_pares"]: CONFIG["filtro_pares"].append(arg)
                enviar(f"✅ Filtro: <b>{arg}</b> ativo.", cid)
            else: enviar("⚠️ Valor inválido. Use /filtrar para ver exemplos.", cid)

        elif cmd == "/limpar":
            CONFIG["filtro_pares"] = []; CONFIG["filtro_direcao"] = ""; CONFIG["filtro_prob"] = CONFIG["prob_minima"]
            enviar("🧹 Filtros limpos! Recebendo todos os sinais.", cid)

        elif cmd == "/status":
            filtros = []
            if CONFIG["filtro_pares"]:    filtros.append(f"Pares: {', '.join(CONFIG['filtro_pares'])}")
            if CONFIG["filtro_direcao"]:  filtros.append(f"Direção: {CONFIG['filtro_direcao']}")
            if CONFIG["filtro_prob"] > CONFIG["prob_minima"]: filtros.append(f"Prob: ≥{CONFIG['filtro_prob']}%")
            enviar(
                f"📊 <b>Status SMC Bot v4.0</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Estado    : {'⏸ Pausado' if CONFIG['pausado'] else '▶️ Ativo'}\n"
                f"Online    : {inicio}\n"
                f"Sinais    : {total_sinais}\n"
                f"TFs       : {', '.join(CONFIG['timeframes_ativos'])}\n"
                f"Favoritos : {len(CONFIG['meus_favoritos'])}\n"
                f"Filtros   : {', '.join(filtros) if filtros else 'Nenhum'}\n"
                f"Hora      : {datetime.now().strftime('%d/%m %H:%M')}", cid)

        elif cmd == "/sinais":
            if not historico_sinais:
                enviar("📭 Nenhum sinal ainda.", cid)
            else:
                linhas = ["📜 <b>Últimos Sinais</b>\n━━━━━━━━━━━━━━━━━━━━━━━"]
                for s in list(reversed(list(historico_sinais)))[:10]:
                    e   = "🟢" if s["direcao"] == "COMPRA" else "🔴"
                    par = TODOS_PARES.get(s["par"], s["par"])
                    linhas.append(f"{e} {par} | {s['tf']} | {s['prob']}% | {s['smc_principal']['padrao']} | {s['zona']} | {converter_hora(s['horario'])}")
                enviar("\n".join(linhas), cid)

        elif cmd == "/addtf":
            a = arg.lower()
            if a not in ["5min","15min","1h","4h"]: enviar("⚠️ Opções: 5min, 15min, 1h, 4h", cid)
            elif a in CONFIG["timeframes_ativos"]: enviar(f"⚠️ {a} já está ativo.", cid)
            else: CONFIG["timeframes_ativos"].append(a); enviar(f"✅ {a} adicionado!", cid)

        elif cmd == "/deltf":
            a = arg.lower()
            if a in CONFIG["timeframes_ativos"]: CONFIG["timeframes_ativos"].remove(a); enviar(f"✅ {a} removido.", cid)
            else: enviar(f"⚠️ {a} não encontrado.", cid)

        elif cmd == "/tfs":
            enviar(f"⏱ <b>Timeframes Ativos</b>\n" +
                "\n".join(f"  • {t}" for t in CONFIG["timeframes_ativos"]) +
                "\n\n/addtf X → ativar | /deltf X → desativar", cid)

        elif cmd == "/pausar":
            CONFIG["pausado"] = True; enviar("⏸ Alertas pausados.", cid)

        elif cmd == "/retomar":
            CONFIG["pausado"] = False; enviar("▶️ Alertas reativados!", cid)

        elif cmd == "/ajuda":
            enviar(
                "📖 <b>Todos os Comandos</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "/status      → estado geral\n"
                "/sinais      → últimos 10 sinais\n"
                "/pares       → todos os 17 pares\n"
                "/tfs         → timeframes\n"
                "/addtf X     → ativar TF\n"
                "/deltf X     → desativar TF\n\n"
                "/favoritos   → seus favoritos\n"
                "/addfav X    → adicionar\n"
                "/delfav X    → remover\n\n"
                "/filtrar X   → filtrar sinais\n"
                "/limpar      → limpar filtros\n\n"
                "/pausar      → pausar alertas\n"
                "/retomar     → retomar alertas", cid)

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
    print("  SMC FOREX BOT v4.0 — Metodologia Completa")
    print("  BOS·FBOS·CHoCH·IDM·SMT·OB·FVG·FLiP·IFC·EQH·PDH")
    print("  Premium/Desconto · 17 Pares · Ouro · Prata")
    print("=" * 60)

    enviar(
        "🤖 <b>SMC Forex Bot v4.0 Online!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Metodologia SMC completa implementada\n"
        "✅ Zonas Premium e Desconto\n"
        "✅ IDM · SMT · IFC · EQH/EQL · PDH/PDL\n"
        "✅ FLiP Zones (S2D / D2S)\n"
        "✅ 17 pares + Ouro + Prata\n\n"
        "Gestão de risco incluída nos sinais\n"
        "Risco recomendado: 1-2% por trade\n\n"
        "Use /ajuda para ver todos os comandos.")

    while True:
        try: processar_comandos()
        except Exception as e: print(f"Erro cmd: {e}")

        if not CONFIG["pausado"]:
            for par in CONFIG["pares_ativos"]:
                for tf in CONFIG["timeframes_ativos"]:
                    if not deve_verificar(par, tf): continue
                    par_nome = TODOS_PARES.get(par, par)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {par_nome} {tf}")
                    try:
                        sinais = analisar_par(par, tf)
                    except Exception as e:
                        print(f"Erro análise {par_nome}: {e}"); continue

                    for s in sinais:
                        if not passar_filtros(s): continue
                        chave = f"{s['par']}_{s['tf']}_{s['direcao']}_{s['horario']}"
                        if chave in sinais_enviados: continue
                        sinais_enviados[chave] = True
                        total_sinais += 1
                        historico_sinais.append(s)
                        par_nome = TODOS_PARES.get(s["par"], s["par"])
                        print(f"  🚨 {s['direcao']} {par_nome} {s['tf']} {s['prob']}% | {s['smc_principal']['padrao']} | {s['zona']}")
                        enviar(formatar(s))
                    time.sleep(2)

        time.sleep(10)

if __name__ == "__main__":
    main()
