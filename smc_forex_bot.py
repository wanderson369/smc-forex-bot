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
    "EUR/USD": "EUR/USD", "GBP/USD": "GBP/USD", "USD/JPY": "USD/JPY",
    "AUD/USD": "AUD/USD", "USD/CHF": "USD/CHF", "USD/CAD": "USD/CAD",
    "NZD/USD": "NZD/USD", "GBP/CAD": "GBP/CAD",
    "EUR/GBP": "EUR/GBP", "EUR/JPY": "EUR/JPY", "GBP/JPY": "GBP/JPY",
    "AUD/JPY": "AUD/JPY", "EUR/AUD": "EUR/AUD", "GBP/AUD": "GBP/AUD",
    "XAU/USD": "XAU/USD",
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
             
