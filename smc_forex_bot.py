"""
SMC Forex Bot — Analista Completo v2.0
========================================
Detecta e combina padrões SMC + Candles japoneses
com cálculo de probabilidade de acerto.

Padrões SMC   : BOS, CHoCH, Order Block, FVG, Liquidity Grab
Candles       : Pin Bar, Engolfo, Harami, Bebê Abandonado,
                Estrela Cadente, Martelo, Doji, 3 Soldados, 3 Corvos
Probabilidade : 50% a 95% baseada em confluências
"""

import os, time, requests, json
from datetime import datetime
from collections import deque

# ============================================================
# CONFIGURAÇÕES
# ============================================================
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")
TWELVE_API_KEY   = os.environ.get("TWELVE_API_KEY", "SUA_CHAVE_AQUI")

PARES = {
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "XAU/USD": "XAUUSD",
}

CONFIG = {
    "velas_analisar":    60,
    "min_movimento_bos": 0.0005,
    "lg_sombra_ratio":   2.0,
    "pausado":           False,
    "timeframes_ativos": ["5min", "15min", "1h"],
    "pares_ativos":      list(PARES.keys()),
    "prob_minima":       55,
}

INTERVALOS = {
    "5min": 300, "15min": 900, "1h": 3600, "4h": 14400,
}

sinais_enviados    = {}
historico_sinais   = deque(maxlen=100)
ultima_verificacao = {}
ultimo_update_id   = 0
inicio             = datetime.now().strftime("%d/%m/%Y %H:%M")
total_sinais       = 0

# ============================================================
# API
# ============================================================
def buscar_candles(par, timeframe, qtd=60):
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
# ANÁLISE DE CANDLE
# ============================================================
def info(v):
    corpo      = abs(v["close"] - v["open"])
    range_     = max(v["high"] - v["low"], 0.00001)
    sombra_sup = v["high"] - max(v["open"], v["close"])
    sombra_inf = min(v["open"], v["close"]) - v["low"]
    return {
        "corpo": corpo, "range": range_,
        "ss": sombra_sup, "si": sombra_inf,
        "alta": v["close"] > v["open"],
        "baixa": v["close"] < v["open"],
        "cp": corpo / range_,
    }

def detectar_candles(c):
    if len(c) < 4:
        return []
    padroes = []
    v1,v2,v3,v4 = c[-4],c[-3],c[-2],c[-1]
    a1,a2,a3,a4 = info(v1),info(v2),info(v3),info(v4)

    # Pin Bar Bullish
    if a4["si"] > a4["corpo"]*2 and a4["cp"] < 0.4 and a4["ss"] < a4["corpo"]:
        padroes.append({"nome":"Pin Bar Bullish","emoji":"📌🟢","dir":"COMPRA","forca":75,
            "desc":"Sombra inferior longa — rejeição de mínimas"})

    # Pin Bar Bearish
    if a4["ss"] > a4["corpo"]*2 and a4["cp"] < 0.4 and a4["si"] < a4["corpo"]:
        padroes.append({"nome":"Pin Bar Bearish","emoji":"📌🔴","dir":"VENDA","forca":75,
            "desc":"Sombra superior longa — rejeição de máximas"})

    # Engolfo Bullish
    if a3["baixa"] and a4["alta"] and v4["open"]<=v3["close"] and v4["close"]>=v3["open"]:
        padroes.append({"nome":"Engolfo Bullish","emoji":"🟢🔥","dir":"COMPRA","forca":82,
            "desc":"Vela de alta engolfa a baixa anterior"})

    # Engolfo Bearish
    if a3["alta"] and a4["baixa"] and v4["open"]>=v3["close"] and v4["close"]<=v3["open"]:
        padroes.append({"nome":"Engolfo Bearish","emoji":"🔴🔥","dir":"VENDA","forca":82,
            "desc":"Vela de baixa engolfa a alta anterior"})

    # Harami Bullish
    if (a3["baixa"] and a4["alta"] and v4["open"]>v3["close"] and
        v4["close"]<v3["open"] and a4["corpo"]<a3["corpo"]*0.5):
        padroes.append({"nome":"Harami Bullish","emoji":"👶🟢","dir":"COMPRA","forca":62,
            "desc":"Vela pequena dentro da grande — possível reversão"})

    # Harami Bearish
    if (a3["alta"] and a4["baixa"] and v4["open"]<v3["close"] and
        v4["close"]>v3["open"] and a4["corpo"]<a3["corpo"]*0.5):
        padroes.append({"nome":"Harami Bearish","emoji":"👶🔴","dir":"VENDA","forca":62,
            "desc":"Vela pequena dentro da grande — possível reversão"})

    # Bebê Abandonado Bullish
    if (a2["baixa"] and a3["cp"]<0.1 and v3["high"]<v2["low"] and
        a4["alta"] and v4["open"]>v3["high"]):
        padroes.append({"nome":"Bebê Abandonado Bullish","emoji":"👶✨🟢","dir":"COMPRA","forca":92,
            "desc":"Doji isolado com gaps — reversão de altíssima probabilidade"})

    # Bebê Abandonado Bearish
    if (a2["alta"] and a3["cp"]<0.1 and v3["low"]>v2["high"] and
        a4["baixa"] and v4["open"]<v3["low"]):
        padroes.append({"nome":"Bebê Abandonado Bearish","emoji":"👶✨🔴","dir":"VENDA","forca":92,
            "desc":"Doji isolado com gaps — reversão de altíssima probabilidade"})

    # Estrela Cadente
    if (a3["alta"] and a4["ss"]>a4["corpo"]*2 and
        a4["si"]<a4["corpo"]*0.5 and v4["open"]>v3["close"]*0.999):
        padroes.append({"nome":"Estrela Cadente","emoji":"🌠🔴","dir":"VENDA","forca":72,
            "desc":"Sombra superior longa após alta — sinal de topo"})

    # Martelo
    if (a3["baixa"] and a4["si"]>a4["corpo"]*2 and a4["ss"]<a4["corpo"]*0.5):
        padroes.append({"nome":"Martelo","emoji":"🔨🟢","dir":"COMPRA","forca":72,
            "desc":"Sombra inferior longa após baixa — sinal de fundo"})

    # Doji
    if a4["cp"] < 0.05:
        padroes.append({"nome":"Doji","emoji":"➕","dir":"NEUTRO","forca":50,
            "desc":"Indecisão — aguardar confirmação"})

    # Três Soldados Brancos
    if (a2["alta"] and a3["alta"] and a4["alta"] and
        v3["close"]>v2["close"] and v4["close"]>v3["close"] and
        a2["cp"]>0.6 and a3["cp"]>0.6 and a4["cp"]>0.6):
        padroes.append({"nome":"Três Soldados Brancos","emoji":"⚔️🟢","dir":"COMPRA","forca":87,
            "desc":"Três altas consecutivas fortes — tendência confirmada"})

    # Três Corvos Negros
    if (a2["baixa"] and a3["baixa"] and a4["baixa"] and
        v3["close"]<v2["close"] and v4["close"]<v3["close"] and
        a2["cp"]>0.6 and a3["cp"]>0.6 and a4["cp"]>0.6):
        padroes.append({"nome":"Três Corvos Negros","emoji":"🦅🔴","dir":"VENDA","forca":87,
            "desc":"Três baixas consecutivas fortes — tendência confirmada"})

    return padroes

# ============================================================
# DETECÇÃO SMC
# ============================================================
def detectar_bos(c):
    if len(c)<22: return []
    sinais=[]
    maxima=max(v["high"] for v in c[-21:-1])
    minima=min(v["low"]  for v in c[-21:-1])
    at=c[-1]; mov=abs(at["close"]-at["open"])
    if at["close"]>maxima and mov>=CONFIG["min_movimento_bos"]:
        sinais.append({"padrao":"BOS","sub":"ALTA","dir":"COMPRA","nivel":maxima,
            "desc":f"Rompimento de estrutura — máxima {maxima:.5f}","peso":30})
    if at["close"]<minima and mov>=CONFIG["min_movimento_bos"]:
        sinais.append({"padrao":"BOS","sub":"BAIXA","dir":"VENDA","nivel":minima,
            "desc":f"Rompimento de estrutura — mínima {minima:.5f}","peso":30})
    return sinais

def detectar_choch(c):
    if len(c)<7: return []
    sinais=[]
    v1,v2,v3,v4,at=c[-5],c[-4],c[-3],c[-2],c[-1]
    if v1["high"]<v2["high"]<v3["high"] and at["close"]<v4["low"]:
        sinais.append({"padrao":"CHoCH","sub":"BAIXA","dir":"VENDA","nivel":v4["low"],
            "desc":f"Mudança de caráter após topos crescentes — rompeu {v4['low']:.5f}","peso":38})
    if v1["low"]>v2["low"]>v3["low"] and at["close"]>v4["high"]:
        sinais.append({"padrao":"CHoCH","sub":"ALTA","dir":"COMPRA","nivel":v4["high"],
            "desc":f"Mudança de caráter após fundos decrescentes — rompeu {v4['high']:.5f}","peso":38})
    return sinais

def detectar_ob(c):
    if len(c)<5: return []
    sinais=[]
    at=c[-1]; ant=c[-2]
    media=sum(abs(v["close"]-v["open"]) for v in c[-6:-1])/5
    corpo=abs(at["close"]-at["open"])
    if corpo<media*1.5: return []
    if at["close"]>at["open"] and ant["close"]<ant["open"]:
        sinais.append({"padrao":"Order Block","sub":"BULLISH","dir":"COMPRA","nivel":ant["low"],
            "desc":f"OB Bullish zona {ant['low']:.5f}–{ant['high']:.5f}","peso":27})
    if at["close"]<at["open"] and ant["close"]>ant["open"]:
        sinais.append({"padrao":"Order Block","sub":"BEARISH","dir":"VENDA","nivel":ant["high"],
            "desc":f"OB Bearish zona {ant['low']:.5f}–{ant['high']:.5f}","peso":27})
    return sinais

def detectar_fvg(c):
    if len(c)<4: return []
    sinais=[]
    v1,v2,v3=c[-3],c[-2],c[-1]
    gap_alta=v3["low"]-v1["high"]
    gap_baixa=v1["low"]-v3["high"]
    if gap_alta>CONFIG["min_movimento_bos"]:
        sinais.append({"padrao":"FVG","sub":"ALTA","dir":"COMPRA","nivel":v1["high"],
            "desc":f"Fair Value Gap {v1['high']:.5f}–{v3['low']:.5f} | Preço tende a preencher","peso":22})
    if gap_baixa>CONFIG["min_movimento_bos"]:
        sinais.append({"padrao":"FVG","sub":"BAIXA","dir":"VENDA","nivel":v1["low"],
            "desc":f"Fair Value Gap {v3['high']:.5f}–{v1['low']:.5f} | Preço tende a preencher","peso":22})
    return sinais

def detectar_lg(c):
    if len(c)<12: return []
    sinais=[]
    max_rec=max(v["high"] for v in c[-12:-2])
    min_rec=min(v["low"]  for v in c[-12:-2])
    sp=c[-2]; at=c[-1]
    ss=sp["high"]-max(sp["open"],sp["close"])
    si=min(sp["open"],sp["close"])-sp["low"]
    co=max(abs(sp["close"]-sp["open"]),0.00001)
    if (sp["high"]>max_rec and ss>co*CONFIG["lg_sombra_ratio"] and
        sp["close"]<max_rec and at["close"]<sp["low"]):
        sinais.append({"padrao":"Liquidity Grab","sub":"BEARISH","dir":"VENDA","nivel":max_rec,
            "desc":f"Caçada de liquidez acima de {max_rec:.5f} — rejeição confirmada","peso":32})
    if (sp["low"]<min_rec and si>co*CONFIG["lg_sombra_ratio"] and
        sp["close"]>min_rec and at["close"]>sp["high"]):
        sinais.append({"padrao":"Liquidity Grab","sub":"BULLISH","dir":"COMPRA","nivel":min_rec,
            "desc":f"Caçada de liquidez abaixo de {min_rec:.5f} — rejeição confirmada","peso":32})
    return sinais

# ============================================================
# MOTOR DE CONFLUÊNCIA E PROBABILIDADE
# ============================================================
def calcular_prob(smc_list, candle_list, direcao):
    pontos = 50
    for s in smc_list:
        if s["dir"]==direcao: pontos+=s["peso"]
    for c in candle_list:
        if c["dir"] in [direcao,"NEUTRO"]: pontos+=c["forca"]//6
    n = sum(1 for s in smc_list if s["dir"]==direcao)
    n += sum(1 for c in candle_list if c["dir"]==direcao)
    if n>=4: pontos+=8
    if n>=6: pontos+=5
    return min(95, max(50, pontos))

def montar_sinais(par, tf, candles, smc_list, candle_list):
    at = candles[-1]
    resultado = []
    for direcao in ["COMPRA","VENDA"]:
        smc_d = [s for s in smc_list if s["dir"]==direcao]
        can_d = [c for c in candle_list if c["dir"]==direcao]
        if not smc_d or not can_d: continue
        prob = calcular_prob(smc_list, candle_list, direcao)
        if prob < CONFIG["prob_minima"]: continue
        resultado.append({
            "par":par,"tf":tf,"direcao":direcao,
            "preco":at["close"],"horario":at["datetime"],
            "prob":prob,"smc":smc_d,"candles":can_d,
        })
    return resultado

def analisar_par(par, tf):
    candles = buscar_candles(par, tf, CONFIG["velas_analisar"])
    if len(candles)<15: return []
    smc_list  = detectar_bos(candles)+detectar_choch(candles)+detectar_ob(candles)+detectar_fvg(candles)+detectar_lg(candles)
    can_list  = detectar_candles(candles)
    return montar_sinais(par, tf, candles, smc_list, can_list)

# ============================================================
# FORMATAÇÃO TELEGRAM
# ============================================================
def barra(prob):
    f=int(prob/10); return "█"*f+"░"*(10-f)

def formatar(s):
    emoji = "🟢📈" if s["direcao"]=="COMPRA" else "🔴📉"
    par   = PARES.get(s["par"], s["par"])
    prob  = s["prob"]
    conf  = "🔥 MUITO ALTO" if prob>=85 else "✅ ALTO" if prob>=70 else "⚡ MÉDIO" if prob>=60 else "⚠️ BAIXO"

    razoes_smc    = "\n".join(f"  🔹 {x['padrao']} {x['sub']}\n      {x['desc']}" for x in s["smc"])
    razoes_candle = "\n".join(f"  {x['emoji']} {x['nome']}\n      {x['desc']}" for x in s["candles"])

    return (
        f"{emoji} <b>SINAL SMC COMPLETO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💱 <b>Par:</b>      {par}\n"
        f"⏱ <b>Timeframe:</b> {s['tf'].upper()}\n"
        f"🎯 <b>Direção:</b>  {s['direcao']}\n"
        f"💰 <b>Preço:</b>    {s['preco']:.5f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Probabilidade: {prob}%</b>\n"
        f"{barra(prob)} {conf}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 <b>Padrões SMC:</b>\n{razoes_smc}\n\n"
        f"🕯 <b>Padrões de Candle:</b>\n{razoes_candle}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {s['horario']}\n"
        f"⚠️ <i>Confirme sempre antes de entrar</i>"
    )

# ============================================================
# TELEGRAM ENVIO E COMANDOS
# ============================================================
def enviar(msg, chat_id=None):
    if TELEGRAM_TOKEN=="SEU_TOKEN_AQUI":
        print(f"[TG]\n{msg}\n"); return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id":chat_id or TELEGRAM_CHAT_ID,"text":msg,
                  "parse_mode":"HTML","disable_web_page_preview":True}, timeout=10)
    except Exception as e:
        print(f"Erro TG: {e}")

def buscar_updates():
    global ultimo_update_id
    if TELEGRAM_TOKEN=="SEU_TOKEN_AQUI": return []
    try:
        r=requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset":ultimo_update_id+1,"timeout":3}, timeout=8)
        upds=r.json().get("result",[])
        if upds: ultimo_update_id=upds[-1]["update_id"]
        return upds
    except: return []

def processar_comandos():
    for u in buscar_updates():
        msg    = u.get("message",{})
        texto  = msg.get("text","").strip()
        cid    = str(msg.get("chat",{}).get("id",""))
        if not texto.startswith("/"): continue
        partes = texto.split(maxsplit=1)
        cmd    = partes[0].lower().split("@")[0]
        arg    = partes[1].strip() if len(partes)>1 else ""
        print(f"[CMD] {texto}")

        if cmd=="/start":
            enviar("🤖 <b>SMC Forex Bot v2.0</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Analista completo SMC + Candles japoneses\n\n"
                "📐 <b>SMC:</b> BOS · CHoCH · OB · FVG · LG\n"
                "🕯 <b>Candles:</b> Pin Bar · Engolfo · Harami\n"
                "   Bebê Abandonado · Martelo · Estrela\n"
                "   Doji · 3 Soldados · 3 Corvos\n\n"
                "📊 Probabilidade calculada por confluência\n\n"
                "/status · /sinais · /pares · /tfs\n"
                "/pausar · /retomar · /ajuda",cid)

        elif cmd=="/status":
            enviar(f"📊 <b>Status SMC Bot v2.0</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Estado   : {'⏸ Pausado' if CONFIG['pausado'] else '▶️ Ativo'}\n"
                f"Online   : {inicio}\n"
                f"Sinais   : {total_sinais}\n"
                f"Pares    : {len(CONFIG['pares_ativos'])}\n"
                f"TFs      : {', '.join(CONFIG['timeframes_ativos'])}\n"
                f"Prob min : {CONFIG['prob_minima']}%\n"
                f"Hora     : {datetime.now().strftime('%d/%m %H:%M')}",cid)

        elif cmd=="/sinais":
            if not historico_sinais:
                enviar("📭 Nenhum sinal ainda.",cid)
            else:
                linhas=["📜 <b>Últimos Sinais</b>\n━━━━━━━━━━━━━━━━━━━━━━━"]
                for s in list(reversed(list(historico_sinais)))[:10]:
                    e="🟢" if s["direcao"]=="COMPRA" else "🔴"
                    linhas.append(f"{e} {PARES.get(s['par'],s['par'])} | {s['tf']} | {s['prob']}% | {s['horario'][-5:]}")
                enviar("\n".join(linhas),cid)

        elif cmd=="/pares":
            enviar("💱 <b>Pares Ativos</b>\n"+"\n".join(f"  • {v}" for v in PARES.values()),cid)

        elif cmd=="/tfs":
            enviar(f"⏱ <b>Timeframes Ativos</b>\n"
                +"\n".join(f"  • {t}" for t in CONFIG["timeframes_ativos"])
                +"\n\nDisponíveis: 5min · 15min · 1h · 4h",cid)

        elif cmd=="/addtf":
            if arg not in ["5min","15min","1h","4h"]:
                enviar("⚠️ Use: /addtf 1h (opções: 5min, 15min, 1h, 4h)",cid)
            elif arg in CONFIG["timeframes_ativos"]:
                enviar(f"⚠️ {arg} já está ativo.",cid)
            else:
                CONFIG["timeframes_ativos"].append(arg)
                enviar(f"✅ {arg} adicionado!",cid)

        elif cmd=="/deltf":
            if arg in CONFIG["timeframes_ativos"]:
                CONFIG["timeframes_ativos"].remove(arg)
                enviar(f"✅ {arg} removido.",cid)
            else:
                enviar(f"⚠️ {arg} não encontrado.",cid)

        elif cmd=="/probmin":
            try:
                novo=int(arg)
                assert 50<=novo<=90
                CONFIG["prob_minima"]=novo
                enviar(f"✅ Probabilidade mínima → {novo}%",cid)
            except:
                enviar("⚠️ Use: /probmin NUMERO (entre 50 e 90)\nEx: /probmin 65",cid)

        elif cmd=="/pausar":
            CONFIG["pausado"]=True
            enviar("⏸ <b>Alertas pausados.</b>",cid)

        elif cmd=="/retomar":
            CONFIG["pausado"]=False
            enviar("▶️ <b>Alertas reativados!</b>",cid)

        elif cmd=="/ajuda":
            enviar("📖 <b>Comandos</b>\n"
                "/status      → estado geral\n"
                "/sinais      → últimos sinais\n"
                "/pares       → pares ativos\n"
                "/tfs         → timeframes\n"
                "/addtf X     → ativar TF\n"
                "/deltf X     → desativar TF\n"
                "/probmin X   → prob mínima (50-90)\n"
                "/pausar      → pausar\n"
                "/retomar     → retomar",cid)

# ============================================================
# LOOP PRINCIPAL
# ============================================================
def deve_verificar(par, tf):
    chave=f"{par}_{tf}"; agora=time.time()
    if agora-ultima_verificacao.get(chave,0)>=INTERVALOS[tf]:
        ultima_verificacao[chave]=agora; return True
    return False

def main():
    global total_sinais
    print("="*55)
    print("  SMC FOREX BOT v2.0 — Analista Completo")
    print("="*55)
    print(f"Pares : {', '.join(PARES.values())}")
    print(f"TFs   : {', '.join(CONFIG['timeframes_ativos'])}")
    print("="*55)

    enviar("🤖 <b>SMC Forex Bot v2.0 Online!</b>\n"
        "Padrões SMC + Candles japoneses\n"
        "Probabilidade por confluência\n\n"
        "Use /ajuda para comandos.")

    while True:
        try: processar_comandos()
        except Exception as e: print(f"Erro cmd: {e}")

        if not CONFIG["pausado"]:
            for par in CONFIG["pares_ativos"]:
                for tf in CONFIG["timeframes_ativos"]:
                    if not deve_verificar(par, tf): continue
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {PARES.get(par,par)} {tf}")
                    try:
                        sinais = analisar_par(par, tf)
                    except Exception as e:
                        print(f"Erro análise: {e}"); continue

                    for s in sinais:
                        chave=f"{s['par']}_{s['tf']}_{s['direcao']}_{s['horario']}"
                        if chave in sinais_enviados: continue
                        sinais_enviados[chave]=True
                        total_sinais+=1
                        historico_sinais.append(s)
                        print(f"  🚨 {s['direcao']} {PARES.get(s['par'],s['par'])} {s['tf']} {s['prob']}%")
                        enviar(formatar(s))
                    time.sleep(2)

        time.sleep(10)

if __name__=="__main__":
    main()
