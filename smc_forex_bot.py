"""
SMC Forex Bot v4.1 — Metodologia Completa
Forex: 19 pares | Crypto: 5 pares (USDT)
TFs: M15, H1 (padrao) | M1 a D1 disponivel
Threads separadas: Analise + Comandos
"""

import os, time, requests, threading
from datetime import datetime, timezone, timedelta
from collections import deque

BRT = timezone(timedelta(hours=-3))

def agora_brt():
    return datetime.now(BRT).strftime("%d/%m %H:%M")

def converter_hora(dt_str):
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).astimezone(BRT).strftime("%d/%m %H:%M")
    except:
        return dt_str

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TWELVE_API_KEY   = os.environ.get("TWELVE_API_KEY",   "")

PARES_FOREX = {
    "EUR/USD": "EUR/USD", "GBP/USD": "GBP/USD", "USD/JPY": "USD/JPY",
    "AUD/USD": "AUD/USD", "USD/CHF": "USD/CHF", "USD/CAD": "USD/CAD",
    "NZD/USD": "NZD/USD", "GBP/CAD": "GBP/CAD",
    "EUR/GBP": "EUR/GBP", "EUR/JPY": "EUR/JPY", "GBP/JPY": "GBP/JPY",
    "AUD/JPY": "AUD/JPY", "EUR/AUD": "EUR/AUD", "GBP/AUD": "GBP/AUD",
    "EUR/CHF": "EUR/CHF", "GBP/CHF": "GBP/CHF",
    "XAU/USD": "XAU/USD", "XAG/USD": "XAG/USD",
}

PARES_CRYPTO = {
    "BTC/USDT": "BTC/USDT", "ETH/USDT": "ETH/USDT",
    "BNB/USDT": "BNB/USDT", "XRP/USDT": "XRP/USDT",
}

TODOS_PARES = {**PARES_FOREX, **PARES_CRYPTO}

CONFIG = {
    "velas_analisar":    60,
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
    "1min": 60, "5min": 300, "15min": 900, "30min": 1800,
    "1h": 3600, "4h": 14400, "1day": 86400,
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
lock               = threading.Lock()

# ============================================================
# API
# ============================================================
def buscar_candles(par, timeframe, qtd=60):
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol": par, "interval": timeframe,
            "outputsize": qtd, "apikey": TWELVE_API_KEY, "format": "JSON",
        }, timeout=10)
        data = r.json()
        if data.get("status") == "error":
            print(f"  API erro {par}: {data.get('message','')[:50]}")
            return []
        return [{"open": float(v["open"]), "high": float(v["high"]),
                 "low":  float(v["low"]),  "close": float(v["close"]),
                 "datetime": v["datetime"]}
                for v in reversed(data.get("values", []))]
    except Exception as e:
        print(f"Erro API {par}: {e}")
        return []

# ============================================================
# UTILITARIOS
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

def mov_min(par):
    if "BTC"  in par: return 50.0
    if "ETH"  in par: return 5.0
    if "BNB"  in par: return 1.0
    if "SOL"  in par: return 0.5
    if "XRP"  in par: return 0.001
    if "XAU"  in par: return 0.5
    if "XAG"  in par: return 0.05
    if "JPY"  in par: return 0.05
    return CONFIG["min_movimento_bos"]

def zona_pd(candles, preco):
    maxima = max(v["high"] for v in candles[-20:])
    minima = min(v["low"]  for v in candles[-20:])
    r = maxima - minima
    if r == 0: return "NEUTRO", 50
    pos = (preco - minima) / r * 100
    if pos >= 62:   return "PREMIUM",    pos
    elif pos <= 38: return "DESCONTO",   pos
    else:           return "EQUILIBRIO", pos

# ============================================================
# DETECCOES SMC
# ============================================================
def det_bos(c, par):
    if len(c) < 22: return []
    at = c[-1]; s = []
    mx = max(v["high"] for v in c[-21:-1])
    mn = min(v["low"]  for v in c[-21:-1])
    if at["close"] > mx:
        f = min(90, 62 + int(((at["close"]-mx)/max(mx,0.0001))*8000))
        s.append({"padrao":"BOS","sub":"ALTA","dir":"COMPRA","nivel":mx,"prob_base":f,
            "desc":f"BOS bullish acima de {mx:.5f}"})
    if at["close"] < mn:
        f = min(90, 62 + int(((mn-at["close"])/max(mn,0.0001))*8000))
        s.append({"padrao":"BOS","sub":"BAIXA","dir":"VENDA","nivel":mn,"prob_base":f,
            "desc":f"BOS bearish abaixo de {mn:.5f}"})
    return s

def det_fbos(c, par):
    if len(c) < 12: return []
    mx = max(v["high"] for v in c[-11:-2])
    mn = min(v["low"]  for v in c[-11:-2])
    sp = c[-2]; at = c[-1]; s = []
    if sp["high"]>mx and sp["close"]<mx and at["close"]<sp["low"]:
        s.append({"padrao":"FBOS/SMT","sub":"BEARISH","dir":"VENDA","nivel":mx,"prob_base":76,
            "desc":f"Fake BOS bearish em {mx:.5f}"})
    if sp["low"]<mn and sp["close"]>mn and at["close"]>sp["high"]:
        s.append({"padrao":"FBOS/SMT","sub":"BULLISH","dir":"COMPRA","nivel":mn,"prob_base":76,
            "desc":f"Fake BOS bullish em {mn:.5f}"})
    return s

def det_choch(c):
    if len(c) < 8: return []
    v1,v2,v3,v4,at = c[-5],c[-4],c[-3],c[-2],c[-1]; s = []
    if v1["high"]<v2["high"]<v3["high"] and at["close"]<v4["low"]:
        idm = v3["high"]<v2["high"]; p = 78 if idm else 68
        s.append({"padrao":"CHoCH","sub":f"BEARISH {'c/IDM' if idm else 's/IDM'}","dir":"VENDA",
            "nivel":v4["low"],"prob_base":p,"desc":f"CHoCH bearish em {v4['low']:.5f}"})
    if v1["low"]>v2["low"]>v3["low"] and at["close"]>v4["high"]:
        idm = v3["low"]>v2["low"]; p = 78 if idm else 68
        s.append({"padrao":"CHoCH","sub":f"BULLISH {'c/IDM' if idm else 's/IDM'}","dir":"COMPRA",
            "nivel":v4["high"],"prob_base":p,"desc":f"CHoCH bullish em {v4['high']:.5f}"})
    return s

def det_ob(c):
    if len(c) < 6: return []
    at=c[-1]; ob=c[-2]; pre=c[-3]; s=[]
    med = sum(abs(v["close"]-v["open"]) for v in c[-7:-1])/6
    cat = abs(at["close"]-at["open"])
    if cat < med*0.8: return []
    if at["close"]>at["open"] and ob["close"]<ob["open"] and ob["low"]<pre["low"] and at["low"]>ob["high"]:
        s.append({"padrao":"Order Block","sub":"BULLISH VALIDO","dir":"COMPRA",
            "nivel":ob["low"],"prob_base":72,"desc":f"OB Bullish {ob['low']:.5f}-{ob['high']:.5f}"})
    elif at["close"]<at["open"] and ob["close"]>ob["open"] and ob["high"]>pre["high"] and at["high"]<ob["low"]:
        s.append({"padrao":"Order Block","sub":"BEARISH VALIDO","dir":"VENDA",
            "nivel":ob["high"],"prob_base":72,"desc":f"OB Bearish {ob['low']:.5f}-{ob['high']:.5f}"})
    elif at["close"]>at["open"] and ob["close"]<ob["open"] and cat>med*1.0:
        s.append({"padrao":"Order Block","sub":"BULLISH","dir":"COMPRA",
            "nivel":ob["low"],"prob_base":62,"desc":f"OB Bullish {ob['low']:.5f}-{ob['high']:.5f}"})
    elif at["close"]<at["open"] and ob["close"]>ob["open"] and cat>med*1.0:
        s.append({"padrao":"Order Block","sub":"BEARISH","dir":"VENDA",
            "nivel":ob["high"],"prob_base":62,"desc":f"OB Bearish {ob['low']:.5f}-{ob['high']:.5f}"})
    return s

def det_fvg(c, par):
    if len(c) < 4: return []
    mn=mov_min(par); v1,v2,v3=c[-3],c[-2],c[-1]; s=[]
    if v3["low"]-v1["high"]>mn:
        s.append({"padrao":"FVG","sub":"BULLISH","dir":"COMPRA","nivel":v1["high"],"prob_base":63,
            "desc":f"Imbalance bullish {v1['high']:.5f}-{v3['low']:.5f}"})
    if v1["low"]-v3["high"]>mn:
        s.append({"padrao":"FVG","sub":"BEARISH","dir":"VENDA","nivel":v1["low"],"prob_base":63,
            "desc":f"Imbalance bearish {v3['high']:.5f}-{v1['low']:.5f}"})
    return s

def det_lg(c, par):
    if len(c) < 12: return []
    mx=max(v["high"] for v in c[-12:-2]); mn=min(v["low"] for v in c[-12:-2])
    sp=c[-2]; at=c[-1]; a=info(sp); co=max(a["corpo"],0.00001); s=[]
    if sp["high"]>mx and a["ss"]>co*CONFIG["lg_sombra_ratio"] and sp["close"]<mx and at["close"]<sp["low"]:
        s.append({"padrao":"Liquidity Grab","sub":"BEARISH","dir":"VENDA","nivel":mx,"prob_base":76,
            "desc":f"Stop hunt acima de {mx:.5f}"})
    if sp["low"]<mn and a["si"]>co*CONFIG["lg_sombra_ratio"] and sp["close"]>mn and at["close"]>sp["high"]:
        s.append({"padrao":"Liquidity Grab","sub":"BULLISH","dir":"COMPRA","nivel":mn,"prob_base":76,
            "desc":f"Stop hunt abaixo de {mn:.5f}"})
    return s

def det_eqh_eql(c, par):
    if len(c) < 10: return []
    at=c[-1]; tol=mov_min(par)*5; s=[]
    maxs=[v["high"] for v in c[-20:-1]]; mins=[v["low"] for v in c[-20:-1]]
    for i in range(len(maxs)-3):
        for j in range(i+2,len(maxs)):
            if abs(maxs[i]-maxs[j])<=tol:
                nv=(maxs[i]+maxs[j])/2
                if at["close"]>nv:
                    s.append({"padrao":"EQH Sweep","dir":"VENDA","nivel":nv,"prob_base":68,
                        "desc":f"Equal Highs varridos em {nv:.5f}"})
                break
    for i in range(len(mins)-3):
        for j in range(i+2,len(mins)):
            if abs(mins[i]-mins[j])<=tol:
                nv=(mins[i]+mins[j])/2
                if at["close"]<nv:
                    s.append({"padrao":"EQL Sweep","dir":"COMPRA","nivel":nv,"prob_base":68,
                        "desc":f"Equal Lows varridos em {nv:.5f}"})
                break
    return s

def det_flip(c):
    if len(c) < 15: return []
    at=c[-1]; s=[]
    for i in range(5,15):
        zh=c[-i]["high"]; zl=c[-i]["low"]
        if at["low"]<=zh and at["close"]>zh and c[-3]["close"]>zh:
            s.append({"padrao":"FLiP S2D","dir":"COMPRA","nivel":zh,"prob_base":70,
                "desc":f"Supply virou Demand em {zh:.5f}"}); break
        if at["high"]>=zl and at["close"]<zl and c[-3]["close"]<zl:
            s.append({"padrao":"FLiP D2S","dir":"VENDA","nivel":zl,"prob_base":70,
                "desc":f"Demand virou Supply em {zl:.5f}"}); break
    return s

def det_ifc(c):
    if len(c) < 15: return []
    sh=max(v["high"] for v in c[-15:-2]); sl=min(v["low"] for v in c[-15:-2])
    sp=c[-2]; at=c[-1]; a=info(sp); s=[]
    if sp["high"]>sh and sp["close"]<sh and a["ss"]>a["corpo"]*1.5 and at["close"]<sp["low"]:
        s.append({"padrao":"IFC Bearish","dir":"VENDA","nivel":sh,"prob_base":78,
            "desc":f"IFC varreu Session High {sh:.5f}"})
    if sp["low"]<sl and sp["close"]>sl and a["si"]>a["corpo"]*1.5 and at["close"]>sp["high"]:
        s.append({"padrao":"IFC Bullish","dir":"COMPRA","nivel":sl,"prob_base":78,
            "desc":f"IFC varreu Session Low {sl:.5f}"})
    return s

def det_idm(c):
    if len(c) < 8: return []
    s=[]
    if c[-5]["high"]<c[-4]["high"] and c[-3]["high"]<c[-4]["high"] and c[-1]["close"]<c[-3]["low"]:
        s.append({"padrao":"IDM Bearish","dir":"VENDA","nivel":c[-4]["high"],"prob_base":73,
            "desc":f"Inducement varrido em {c[-4]['high']:.5f}"})
    if c[-5]["low"]>c[-4]["low"] and c[-3]["low"]>c[-4]["low"] and c[-1]["close"]>c[-3]["high"]:
        s.append({"padrao":"IDM Bullish","dir":"COMPRA","nivel":c[-4]["low"],"prob_base":73,
            "desc":f"Inducement varrido em {c[-4]['low']:.5f}"})
    return s

def det_candles(c):
    if len(c) < 4: return []
    p=[]; v1,v2,v3,v4=c[-4],c[-3],c[-2],c[-1]; a1,a2,a3,a4=info(v1),info(v2),info(v3),info(v4)
    if a4["si"]>a4["corpo"]*2 and a4["cp"]<0.4 and a4["ss"]<a4["corpo"]:
        p.append({"nome":"Pin Bar Bullish","emoji":"📌🟢","dir":"COMPRA","bonus":10})
    if a4["ss"]>a4["corpo"]*2 and a4["cp"]<0.4 and a4["si"]<a4["corpo"]:
        p.append({"nome":"Pin Bar Bearish","emoji":"📌🔴","dir":"VENDA","bonus":10})
    if a3["baixa"] and a4["alta"] and v4["open"]<=v3["close"] and v4["close"]>=v3["open"]:
        p.append({"nome":"Engolfo Bullish","emoji":"🟢🔥","dir":"COMPRA","bonus":13})
    if a3["alta"] and a4["baixa"] and v4["open"]>=v3["close"] and v4["close"]<=v3["open"]:
        p.append({"nome":"Engolfo Bearish","emoji":"🔴🔥","dir":"VENDA","bonus":13})
    if a3["baixa"] and a4["alta"] and v4["open"]>v3["close"] and v4["close"]<v3["open"] and a4["corpo"]<a3["corpo"]*0.5:
        p.append({"nome":"Harami Bullish","emoji":"👶🟢","dir":"COMPRA","bonus":7})
    if a3["alta"] and a4["baixa"] and v4["open"]<v3["close"] and v4["close"]>v3["open"] and a4["corpo"]<a3["corpo"]*0.5:
        p.append({"nome":"Harami Bearish","emoji":"👶🔴","dir":"VENDA","bonus":7})
    if a2["baixa"] and a3["cp"]<0.1 and v3["high"]<v2["low"] and a4["alta"] and v4["open"]>v3["high"]:
        p.append({"nome":"Bebe Abandonado Bullish","emoji":"👶✨🟢","dir":"COMPRA","bonus":18})
    if a2["alta"] and a3["cp"]<0.1 and v3["low"]>v2["high"] and a4["baixa"] and v4["open"]<v3["low"]:
        p.append({"nome":"Bebe Abandonado Bearish","emoji":"👶✨🔴","dir":"VENDA","bonus":18})
    if a3["alta"] and a4["ss"]>a4["corpo"]*2 and a4["si"]<a4["corpo"]*0.5:
        p.append({"nome":"Estrela Cadente","emoji":"🌠🔴","dir":"VENDA","bonus":9})
    if a3["baixa"] and a4["si"]>a4["corpo"]*2 and a4["ss"]<a4["corpo"]*0.5:
        p.append({"nome":"Martelo","emoji":"🔨🟢","dir":"COMPRA","bonus":9})
    if a4["cp"]<0.05:
        p.append({"nome":"Doji","emoji":"➕","dir":"NEUTRO","bonus":4})
    if a2["alta"] and a3["alta"] and a4["alta"] and v3["close"]>v2["close"] and v4["close"]>v3["close"] and a2["cp"]>0.6 and a3["cp"]>0.6 and a4["cp"]>0.6:
        p.append({"nome":"Tres Soldados","emoji":"⚔️🟢","dir":"COMPRA","bonus":14})
    if a2["baixa"] and a3["baixa"] and a4["baixa"] and v3["close"]<v2["close"] and v4["close"]<v3["close"] and a2["cp"]>0.6 and a3["cp"]>0.6 and a4["cp"]>0.6:
        p.append({"nome":"Tres Corvos","emoji":"🦅🔴","dir":"VENDA","bonus":14})
    return p

# ============================================================
# MOTOR
# ============================================================
def analisar_par(par, tf):
    c = buscar_candles(par, tf, CONFIG["velas_analisar"])
    if len(c) < 20: return []
    at = c[-1]
    zona, zona_pct = zona_pd(c, at["close"])
    smc = (det_bos(c,par)+det_fbos(c,par)+det_choch(c)+det_idm(c)+
           det_ifc(c)+det_ob(c)+det_fvg(c,par)+det_flip(c)+
           det_lg(c,par)+det_eqh_eql(c,par))
    can = det_candles(c)
    fins = []
    for s in smc:
        d=s["dir"]; p=s["prob_base"]
        if d=="COMPRA" and zona=="DESCONTO": p+=8
        elif d=="VENDA" and zona=="PREMIUM":  p+=8
        elif d=="COMPRA" and zona=="PREMIUM": p-=10
        elif d=="VENDA" and zona=="DESCONTO": p-=10
        cf=[x for x in can if x["dir"] in [d,"NEUTRO"]]
        p+=sum(x["bonus"] for x in cf)
        outros=[x for x in smc if x["dir"]==d and x["padrao"]!=s["padrao"]]
        p+=len(outros)*5
        p=min(95,max(50,p))
        if p<CONFIG["prob_minima"]: continue
        fins.append({"par":par,"tf":tf,"direcao":d,"preco":at["close"],
            "horario":at["datetime"],"prob":p,"zona":zona,"zona_pct":zona_pct,
            "smc_principal":s,"outros_smc":outros,"candles":cf})
    unicos={}
    for s in fins:
        k=f"{s['par']}_{s['tf']}_{s['direcao']}"
        if k not in unicos or s["prob"]>unicos[k]["prob"]: unicos[k]=s
    return list(unicos.values())

def passar_filtros(s):
    if CONFIG["filtro_pares"]   and s["par"] not in CONFIG["filtro_pares"]:   return False
    if CONFIG["meus_favoritos"] and s["par"] not in CONFIG["meus_favoritos"]: return False
    if CONFIG["filtro_direcao"] and s["direcao"]!=CONFIG["filtro_direcao"]:   return False
    if s["prob"]<CONFIG["filtro_prob"]: return False
    return True

# ============================================================
# FORMATACAO
# ============================================================
def barra(p):
    f=int(p/10); return "█"*f+"░"*(10-f)

def formatar(s):
    e  = "🟢📈" if s["direcao"]=="COMPRA" else "🔴📉"
    p  = s["prob"]
    cf = "🔥 MUITO ALTO" if p>=85 else "✅ ALTO" if p>=70 else "⚡ MEDIO" if p>=60 else "⚠️ BAIXO"
    sm = s["smc_principal"]
    tn = TF_NOMES.get(s["tf"],s["tf"])
    zt = {"PREMIUM":"🔴 PREMIUM","DESCONTO":"🟢 DESCONTO","EQUILIBRIO":"⚖️ EQUILIBRIO"}.get(s["zona"],s["zona"])
    st = "Abaixo do OB/FVG" if s["direcao"]=="COMPRA" else "Acima do OB/FVG"
    ot = ""
    if s["outros_smc"]:
        ot="\n🔹 <b>Confluencias:</b>\n"+"".join(f"  • {x['padrao']}\n" for x in s["outros_smc"][:3])
    ct=""
    if s["candles"]:
        ct="\n🕯 <b>Candle:</b>\n"+"".join(f"  {x['emoji']} {x['nome']}\n" for x in s["candles"][:2])
    return (
        f"{e} <b>SINAL SMC — {s['par']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💱 Par:       {s['par']}\n"
        f"⏱ Timeframe: {tn}\n"
        f"🎯 Direcao:   {s['direcao']}\n"
        f"💰 Preco:     {s['preco']:.5f}\n"
        f"🗺 Zona:     {zt} ({s['zona_pct']:.0f}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Probabilidade: {p}%</b>\n"
        f"{barra(p)} {cf}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 <b>Padrao:</b> {sm['padrao']} {sm.get('sub','')}\n"
        f"   {sm['desc']}\n"
        f"{ot}{ct}"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Stop: {st} | RR: 1:5-1:10\n"
        f"🕐 {converter_hora(s['horario'])} (Brasilia)\n"
        f"<i>Confirme antes de entrar</i>"
    )

# ============================================================
# TELEGRAM
# ============================================================
def enviar(msg, chat_id=None):
    if not TELEGRAM_TOKEN: print(f"[TG] {msg[:80]}"); return
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
    if not TELEGRAM_TOKEN: return []
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": ultimo_update_id+1, "timeout": 1}, timeout=5)
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
        arg    = partes[1].strip().upper() if len(partes)>1 else ""

        if cmd == "/start":
            enviar("🤖 <b>SMC Forex Bot v4.1</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅ 19 pares Forex + 5 Crypto\n"
                "✅ BOS/FBOS/CHoCH/IDM/OB/FVG\n"
                "✅ FLiP/IFC/EQH/LG\n"
                "✅ Zonas Premium e Desconto\n"
                "✅ M15 e H1 por padrao\n\n"
                "Regra:\n"
                "🟢 COMPRA + DESCONTO + 70%\n"
                "🔴 VENDA  + PREMIUM  + 70%\n\n"
                "/ajuda → todos os comandos", cid)

        elif cmd == "/pares":
            enviar("💱 <b>Forex (19)</b>\n"
   
