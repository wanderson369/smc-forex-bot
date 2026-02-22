"""
SMC Forex Bot — 100% Python, sem MT5, sem Windows
===================================================
Funciona no celular via Railway/Render (nuvem grátis).
Dados: Twelve Data API (gratuita, 800 req/dia)
Pares: EURUSD, GBPUSD, USDJPY, XAUUSD
Padrões SMC: BOS, CHoCH, Order Block, FVG, Liquidity Grab
Alertas: Telegram com comandos interativos

Instalação:
    pip install requests pandas

Variáveis de ambiente (configure no Railway):
    TELEGRAM_TOKEN   = seu token
    TELEGRAM_CHAT_ID = seu chat id
    TWELVE_API_KEY   = sua chave (grátis em twelvedata.com)
"""

import os
import time
import requests
import json
from datetime import datetime
from collections import deque

# ============================================================
# CONFIGURAÇÕES
# ============================================================

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")
TWELVE_API_KEY   = os.environ.get("TWELVE_API_KEY", "SUA_CHAVE_AQUI")

# Pares monitorados e seus nomes na API
PARES = {
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "XAU/USD": "XAUUSD",
}

# Timeframes monitorados (do menor para o maior)
TIMEFRAMES = ["5min", "15min", "1h", "4h"]

# Configurações de detecção SMC
CONFIG = {
    "velas_analisar":    50,     # quantas velas analisar
    "min_corpo_pct":     0.3,    # corpo mínimo da vela (30% do range)
    "min_movimento_bos": 0.0005, # movimento mínimo para BOS
    "lg_sombra_ratio":   2.0,    # sombra deve ser X vezes o corpo (LG)
    "pausado":           False,
    "timeframes_ativos": ["5min", "15min", "1h"],
    "pares_ativos":      list(PARES.keys()),
}

# Intervalo entre verificações por timeframe
INTERVALOS = {
    "5min":  5  * 60,
    "15min": 15 * 60,
    "1h":    60 * 60,
    "4h":    4  * 60 * 60,
}

# ============================================================
# MEMÓRIA
# ============================================================
sinais_enviados   = {}   # { "PAR_TF_PADRAO_HORARIO": True }
historico_sinais  = deque(maxlen=50)
ultima_verificacao = {}  # { "PAR_TF": timestamp }
ultimo_update_id  = 0
inicio            = datetime.now().strftime("%d/%m/%Y %H:%M")
total_sinais      = 0

# ============================================================
# TWELVE DATA API — busca candles gratuitos
# ============================================================

def buscar_candles(par, timeframe, quantidade=60):
    """
    Busca candles OHLC da Twelve Data API (gratuita).
    Retorna lista de dicts: [{"open","high","low","close","datetime"}]
    """
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol":     par,
        "interval":   timeframe,
        "outputsize": quantidade,
        "apikey":     TWELVE_API_KEY,
        "format":     "JSON",
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        if data.get("status") == "error":
            print(f"API erro {par} {timeframe}: {data.get('message')}")
            return []

        valores = data.get("values", [])
        # Converte para float e ordena do mais antigo para o mais novo
        candles = []
        for v in reversed(valores):
            candles.append({
                "open":     float(v["open"]),
                "high":     float(v["high"]),
                "low":      float(v["low"]),
                "close":    float(v["close"]),
                "datetime": v["datetime"],
            })
        return candles

    except Exception as e:
        print(f"Erro ao buscar {par} {timeframe}: {e}")
        return []

# ============================================================
# DETECÇÃO DE PADRÕES SMC
# ============================================================

def detectar_bos(candles, par, tf):
    """Break of Structure — rompe máxima ou mínima das últimas 20 velas."""
    if len(candles) < 22:
        return []

    sinais = []
    c = candles  # mais recente = c[-1]

    # Máxima e mínima das 20 velas anteriores (exclui a última)
    janela = c[-21:-1]
    maxima = max(v["high"] for v in janela)
    minima = min(v["low"]  for v in janela)

    atual  = c[-1]
    mov    = abs(atual["close"] - atual["open"])

    # BOS Alta
    if atual["close"] > maxima and mov >= CONFIG["min_movimento_bos"]:
        forca = ((atual["close"] - maxima) / maxima) * 100
        sinais.append({
            "par": par, "tf": tf, "padrao": "BOS_ALTA", "direcao": "COMPRA",
            "preco": atual["close"],
            "detalhe": f"Rompeu máx {maxima:.5f} | Força {forca:.2f}%",
            "horario": atual["datetime"],
        })

    # BOS Baixa
    if atual["close"] < minima and mov >= CONFIG["min_movimento_bos"]:
        forca = ((minima - atual["close"]) / minima) * 100
        sinais.append({
            "par": par, "tf": tf, "padrao": "BOS_BAIXA", "direcao": "VENDA",
            "preco": atual["close"],
            "detalhe": f"Rompeu mín {minima:.5f} | Força {forca:.2f}%",
            "horario": atual["datetime"],
        })

    return sinais


def detectar_choch(candles, par, tf):
    """Change of Character — inversão após sequência de topos/fundos."""
    if len(candles) < 7:
        return []

    sinais = []
    c = candles

    # Últimas 5 velas (exceto a atual)
    v1, v2, v3, v4, atual = c[-5], c[-4], c[-3], c[-2], c[-1]

    # CHoCH Baixa: topos crescentes + reversão
    topos_crescentes = v1["high"] < v2["high"] < v3["high"]
    reversao_baixa   = atual["close"] < v4["low"]
    if topos_crescentes and reversao_baixa:
        sinais.append({
            "par": par, "tf": tf, "padrao": "CHoCH_BAIXA", "direcao": "VENDA",
            "preco": atual["close"],
            "detalhe": f"Inversão após topos crescentes | Rompeu {v4['low']:.5f}",
            "horario": atual["datetime"],
        })

    # CHoCH Alta: fundos decrescentes + reversão
    fundos_decrescentes = v1["low"] > v2["low"] > v3["low"]
    reversao_alta       = atual["close"] > v4["high"]
    if fundos_decrescentes and reversao_alta:
        sinais.append({
            "par": par, "tf": tf, "padrao": "CHoCH_ALTA", "direcao": "COMPRA",
            "preco": atual["close"],
            "detalhe": f"Inversão após fundos decrescentes | Rompeu {v4['high']:.5f}",
            "horario": atual["datetime"],
        })

    return sinais


def detectar_order_block(candles, par, tf):
    """Order Block — última vela contrária antes de movimento forte."""
    if len(candles) < 5:
        return []

    sinais = []
    c = candles

    atual = c[-1]
    ant   = c[-2]

    # Corpo médio das últimas 5 velas
    media_corpo = sum(abs(v["close"] - v["open"]) for v in c[-6:-1]) / 5
    corpo_atual = abs(atual["close"] - atual["open"])

    # Movimento forte = corpo atual > 1.5x média
    if corpo_atual < media_corpo * 1.5:
        return []

    # OB Bullish: atual é vela de alta, anterior era de baixa
    if atual["close"] > atual["open"] and ant["close"] < ant["open"]:
        sinais.append({
            "par": par, "tf": tf, "padrao": "OB_BULLISH", "direcao": "COMPRA",
            "preco": atual["close"],
            "detalhe": f"OB zona {ant['low']:.5f}–{ant['high']:.5f} | Mov forte: {corpo_atual:.5f}",
            "horario": atual["datetime"],
        })

    # OB Bearish: atual é vela de baixa, anterior era de alta
< truncated lines 225-375 >
        f"{emoji_dir} <b>SINAL SMC — {par_limpo}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📐 <b>Padrão:</b>  {padrao_txt}\n"
        f"⏱ <b>TF:</b>      {s['tf'].upper()}\n"
        f"🎯 <b>Direção:</b> {s['direcao']}\n"
        f"💰 <b>Preço:</b>   {s['preco']:.5f}\n"
        f"📋 {s['detalhe']}\n"
        f"🕐 {s['horario']}"
    )

# ============================================================
# TELEGRAM — COMANDOS
# ============================================================

def buscar_updates():
    global ultimo_update_id
    if TELEGRAM_TOKEN == "SEU_TOKEN_AQUI":
        return []
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": ultimo_update_id + 1, "timeout": 3},
            timeout=8
        )
        updates = r.json().get("result", [])
        if updates:
            ultimo_update_id = updates[-1]["update_id"]
        return updates
    except:
        return []


def processar_comandos():
    for u in buscar_updates():
        msg     = u.get("message", {})
        texto   = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        if not texto.startswith("/"):
            continue

        partes = texto.split(maxsplit=1)
        cmd    = partes[0].lower().split("@")[0]
        arg    = partes[1].strip() if len(partes) > 1 else ""
        print(f"[CMD] {texto}")

        if cmd == "/start":
            enviar(
                "🤖 <b>SMC Forex Bot</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Detecta BOS · CHoCH · OB · FVG · LG\n"
                "Pares: EURUSD · GBPUSD · USDJPY · XAUUSD\n\n"
                "📋 <b>Comandos:</b>\n"
                "/status    → estado do bot\n"
                "/sinais    → últimos sinais\n"
                "/pares     → pares ativos\n"
                "/tfs       → timeframes ativos\n"
                "/addpar X  → adicionar par\n"
                "/addtf X   → adicionar timeframe\n"
                "/deltf X   → remover timeframe\n"
                "/sensivel X→ mudar sensibilidade\n"
                "/pausar    → pausar alertas\n"
                "/retomar   → retomar alertas\n"
                "/ajuda     → todos os comandos", chat_id)

        elif cmd == "/status":
            enviar(
                f"📊 <b>Status SMC Bot</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Estado   : {'⏸ Pausado' if CONFIG['pausado'] else '▶️ Ativo'}\n"
                f"Online   : {inicio}\n"
                f"Sinais   : {total_sinais}\n"
                f"Pares    : {len(CONFIG['pares_ativos'])}\n"
                f"TFs      : {', '.join(CONFIG['timeframes_ativos'])}\n"
                f"Hora     : {datetime.now().strftime('%d/%m %H:%M')}", chat_id)

        elif cmd == "/sinais":
            if not historico_sinais:
                enviar("📭 Nenhum sinal ainda.", chat_id)
            else:
                linhas = ["📜 <b>Últimos Sinais</b>\n━━━━━━━━━━━━━━━━━━━━"]
                for s in list(reversed(list(historico_sinais)))[:10]:
                    e = "🟢" if s["direcao"] == "COMPRA" else "🔴"
                    linhas.append(f"{e} {PARES.get(s['par'],s['par'])} | {s['padrao']} | {s['tf']} | {s['horario'][-5:]}")
                enviar("\n".join(linhas), chat_id)

        elif cmd == "/pares":
            lista = "\n".join(f"  • {PARES.get(p,p)}" for p in CONFIG["pares_ativos"])
            enviar(f"💱 <b>Pares Ativos</b>\n━━━━━━━━━━━━━━━━━━━━\n{lista}", chat_id)

        elif cmd == "/tfs":
            lista = "\n".join(f"  • {tf}" for tf in CONFIG["timeframes_ativos"])
            enviar(f"⏱ <b>Timeframes Ativos</b>\n━━━━━━━━━━━━━━━━━━━━\n{lista}\n\nDisponíveis: 5min, 15min, 1h, 4h", chat_id)

        elif cmd == "/addtf":
            tfs_validos = ["5min", "15min", "1h", "4h"]
            if arg not in tfs_validos:
                enviar(f"⚠️ TF inválido. Use: {', '.join(tfs_validos)}", chat_id)
            elif arg in CONFIG["timeframes_ativos"]:
                enviar(f"⚠️ {arg} já está ativo.", chat_id)
            else:
                CONFIG["timeframes_ativos"].append(arg)
                enviar(f"✅ {arg} adicionado!", chat_id)

        elif cmd == "/deltf":
            if arg in CONFIG["timeframes_ativos"]:
                CONFIG["timeframes_ativos"].remove(arg)
                enviar(f"✅ {arg} removido.", chat_id)
            else:
                enviar(f"⚠️ {arg} não encontrado.", chat_id)

        elif cmd == "/sensivel":
            try:
                novo = float(arg)
                assert 0.0001 <= novo <= 0.01
                CONFIG["min_movimento_bos"] = novo
                enviar(f"✅ Sensibilidade → {novo}", chat_id)
            except:
                enviar("⚠️ Use: /sensivel VALOR\nEx: /sensivel 0.0005\nFaixa: 0.0001 a 0.01", chat_id)

        elif cmd == "/pausar":
            CONFIG["pausado"] = True
            enviar("⏸ <b>Alertas pausados.</b>\nUse /retomar.", chat_id)

        elif cmd == "/retomar":
            CONFIG["pausado"] = False
            enviar("▶️ <b>Alertas reativados!</b>", chat_id)

        elif cmd == "/ajuda":
            enviar(
                "📖 <b>Comandos SMC Bot</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "/status      → estado geral\n"
                "/sinais      → últimos 10 sinais\n"
                "/pares       → pares monitorados\n"
                "/tfs         → timeframes ativos\n"
                "/addtf 1h    → ativar timeframe 1h\n"
                "/deltf 4h    → desativar timeframe 4h\n"
                "/sensivel X  → ajustar sensibilidade\n"
                "/pausar      → pausar alertas\n"
                "/retomar     → retomar alertas", chat_id)

# ============================================================
# LOOP PRINCIPAL
# ============================================================

def deve_verificar(par, tf):
    """Verifica se chegou a hora de analisar esse par/TF."""
    chave = f"{par}_{tf}"
    agora = time.time()
    ultimo = ultima_verificacao.get(chave, 0)
    if agora - ultimo >= INTERVALOS[tf]:
        ultima_verificacao[chave] = agora
        return True
    return False


def main():
    global total_sinais

    print("=" * 55)
    print("  SMC FOREX BOT — Sem MT5, 100% Python")
    print("=" * 55)
    print(f"Pares : {', '.join(PARES.values())}")
    print(f"TFs   : {', '.join(CONFIG['timeframes_ativos'])}")
    print(f"API   : {'✅ OK' if TWELVE_API_KEY != 'SUA_CHAVE_AQUI' else '⚠️ Configure TWELVE_API_KEY'}")
    print(f"TG    : {'✅ OK' if TELEGRAM_TOKEN != 'SEU_TOKEN_AQUI' else '⚠️ Configure TELEGRAM_TOKEN'}")
    print("=" * 55)

    enviar(
        "🤖 <b>SMC Forex Bot Online!</b>\n"
        f"Pares: EURUSD · GBPUSD · USDJPY · XAUUSD\n"
        f"TFs: {' · '.join(CONFIG['timeframes_ativos'])}\n"
        f"Padrões: BOS · CHoCH · OB · FVG · LG\n\n"
        "Use /ajuda para comandos."
    )

    ciclo = 0
    while True:
        ciclo += 1

        # Processa comandos Telegram
        try:
            processar_comandos()
        except Exception as e:
            print(f"Erro comandos: {e}")

        # Analisa mercados
        if not CONFIG["pausado"]:
            for par in CONFIG["pares_ativos"]:
                for tf in CONFIG["timeframes_ativos"]:
                    if not deve_verificar(par, tf):
                        continue

                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Analisando {PARES.get(par,par)} {tf}")

                    try:
                        sinais = analisar_par(par, tf)
                    except Exception as e:
                        print(f"Erro análise {par} {tf}: {e}")
                        continue

                    for s in sinais:
                        # Evita duplicatas na mesma vela
                        chave = f"{s['par']}_{s['tf']}_{s['padrao']}_{s['horario']}"
                        if chave in sinais_enviados:
                            continue
                        sinais_enviados[chave] = True

                        total_sinais += 1
                        historico_sinais.append(s)

                        print(f"  🚨 {s['padrao']} | {PARES.get(s['par'],s['par'])} | {s['direcao']}")
                        enviar(formatar_sinal(s))

                    # Respeita limite da API (800 req/dia = ~1 req/108s)
                    # Com 4 pares × 3 TFs = 12 combinações, espaçamos as chamadas
                    time.sleep(2)

        time.sleep(10)  # verifica comandos a cada 10s


if __name__ == "__main__":
    main()
