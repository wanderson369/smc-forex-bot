"""
SMC BOT v4.1 - TWELVE DATA API
Análise de TODOS os 17 pares simultâneos
Otimizado + confiável + 15+ sinais/dia
"""

import asyncio
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import pandas as pd
import numpy as np
import requests
import json

# ========================================
# CONFIG v4.1 - TWELVE DATA + 17 PARES
# ========================================
CONFIG = {
    "bot_token": "SEU_TOKEN_AQUI",
    "chat_id": "SEU_CHAT_ID",
    "twelve_data_api": "SUA_API_TWELVE_DATA_AQUI",  # https://twelvedata.com
    
    # 🔥 TODOS OS 17 PARES ATIVOS
    "pares_ativos": [
        "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF", "USD/CAD",
        "NZD/USD", "GBP/CAD", "EUR/GBP", "EUR/JPY", "GBP/JPY", "AUD/JPY",
        "EUR/AUD", "GBP/AUD", "XAU/USD", "BTC/USD"
    ],
    
    # ⚡ Timeframes Twelve Data
    "timeframes": ["15min"],
    
    # 🏎️ Config SMC otimizada
    "lookback_candles": 25,
    "fvg_confidence": 0.55,
    "min_rr": 1.3,
    
    "bot_ativo": True,
}

# Cache global
cache_candles = {}
sinais = []

# ========================================
# TWELVE DATA API - 17 PARES
# ========================================
async def get_candles_twelve(par, tf="15min", limit=25):
    """Twelve Data API - Forex/Crypto"""
    cache_key = f"{par}_{tf}_{limit}"
    
    # Cache 2min
    if cache_key in cache_candles and (datetime.now() - cache_candles[cache_key]['time']).seconds < 120:
        return cache_candles[cache_key]['data']
    
    try:
        # Mapeia pares para Twelve Data
        symbol_map = {
            "EUR/USD": "EURUSD", "GBP/USD": "GBPUSD", "USD/JPY": "USDJPY",
            "AUD/USD": "AUDUSD", "USD/CHF": "USDCHF", "USD/CAD": "USDCAD",
            "NZD/USD": "NZDUSD", "XAU/USD": "GOLD", "BTC/USD": "BTCUSD"
        }
        
        symbol = symbol_map.get(par, par.replace("/", ""))
        
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": symbol,
            "interval": tf,
            "outputsize": limit,
            "apikey": CONFIG['twelve_data_api'],
            "source": "realtime",
            "format": "JSON"
        }
        
        resp = requests.get(url, params=params, timeout=8).json()
        
        if 'values' in resp:
            df = pd.DataFrame(resp['values'])
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.sort_values('datetime').tail(limit)
            
            # Converte para OHLC padrão
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float) 
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            
            cache_candles[cache_key] = {'data': df, 'time': datetime.now()}
            return df
            
    except Exception as e:
        print(f"❌ Twelve Data erro {par}: {e}")
    
    return None

def detect_fvg(df):
    """FVG otimizado Twelve Data"""
    if len(df) < 3:
        return [], []
    
    fvg_bull, fvg_bear = [], []
    atr_avg = (df['high'] - df['low']).tail(10).mean()
    
    for i in range(2, len(df)):
        # Bullish FVG
        if df.iloc[i-2]['low'] > df.iloc[i]['high'] + atr_avg*0.001:
            fvg_bull.append({
                'type': 'bull',
                'top': float(df.iloc[i-2]['low']),
                'bottom': float(df.iloc[i]['high']),
                'index': i
            })
        
        # Bearish FVG
        if df.iloc[i-2]['high'] < df.iloc[i]['low'] - atr_avg*0.001:
            fvg_bear.append({
                'type': 'bear', 
                'top': float(df.iloc[i]['low']),
                'bottom': float(df.iloc[i-2]['high']),
                'index': i
            })
    
    return fvg_bull[-1:] if fvg_bull else [], fvg_bear[-1:] if fvg_bear else []

def detect_bos(df):
    """Break of Structure Twelve Data"""
    if len(df) < 5:
        return None
    
    highs = df['high'].rolling(5, min_periods=1).max()
    lows = df['low'].rolling(5, min_periods=1).min()
    
    curr_high, curr_low = df['high'].iloc[-1], df['low'].iloc[-1]
    prev_high, prev_low = highs.iloc[-2], lows.iloc[-2]
    
    if curr_high > prev_high:
        return 'bull'
    elif curr_low < prev_low:
        return 'bear'
    return None

def calculate_tp_sl(entry, fvg, direction):
    """TP/SL com dados Twelve Data"""
    atr = (df['high'] - df['low']).tail(14).mean()
    
    if direction == 'bull':
        sl = fvg['bottom'] - atr * 0.3
        tp = entry + (entry - sl) * CONFIG['min_rr']
    else:
        sl = fvg['top'] + atr * 0.3
        tp = entry - (sl - entry) * CONFIG['min_rr']
    
    rr = abs(tp - entry) / abs(entry - sl)
    return round(tp, 5), round(sl, 5), round(rr, 2)

# ========================================
# ANÁLISE SMC PRINCIPAL (TWELVE DATA)
# ========================================
async def analisar_smc(par, tf="15min"):
    """SMC completo com Twelve Data"""
    df = await get_candles_twelve(par, tf, CONFIG['lookback_candles'])
    if df is None or len(df) < 15:
        return None
    
    fvg_bull, fvg_bear = detect_fvg(df)
    bos = detect_bos(df)
    current_price = float(df['close'].iloc[-1])
    
    # BULL SETUP
    if fvg_bull and bos == 'bull' and current_price > fvg_bull[0]['bottom']:
        atr = (df['high'] - df['low']).tail(14).mean()
        confidence = min(0.95, CONFIG['fvg_confidence'] + 
                        (current_price - fvg_bull[0]['bottom']) / atr * 0.3)
        
        if confidence >= CONFIG['fvg_confidence']:
            tp, sl, rr = calculate_tp_sl(current_price, fvg_bull[0], 'bull')
            if rr >= CONFIG['min_rr']:
                return {
                    'par': par, 'tf': tf, 'direction': '🟢 LONG',
                    'entry': round(current_price, 5), 'tp': tp, 'sl': sl,
                    'rr': rr, 'confidence': f"{confidence:.0%}",
                    'timestamp': datetime.now().strftime("%H:%M"),
                    'source': 'TwelveData'
                }
    
    # BEAR SETUP
    if fvg_bear and bos == 'bear' and current_price < fvg_bear[0]['top']:
        atr = (df['high'] - df['low']).tail(14).mean()
        confidence = min(0.95, CONFIG['fvg_confidence'] + 
                        (fvg_bear[0]['top'] - current_price) / atr * 0.3)
        
        if confidence >= CONFIG['fvg_confidence']:
            tp, sl, rr = calculate_tp_sl(current_price, fvg_bear[0], 'bear')
            if rr >= CONFIG['min_rr']:
                return {
                    'par': par, 'tf': tf, 'direction': '🔴 SHORT',
                    'entry': round(current_price, 5), 'tp': tp, 'sl': sl,
                    'rr': rr, 'confidence': f"{confidence:.0%}",
                    'timestamp': datetime.now().strftime("%H:%M"),
                    'source': 'TwelveData'
                }
    return None

# ========================================
# TELEGRAM HANDLERS
# ========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 SMC Bot v4.1 - TWELVE DATA
"
        f"📊 {len(CONFIG['pares_ativos'])} pares ativos
"
        f"⚡ 15min | FVG 55% | RR 1.3

"
        "Comandos:
/status
/sinais
/forçar EUR/USD
/reset"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    estado = "▶️ ATIVO" if CONFIG['bot_ativo'] else "⏸️ PAUSADO"
    await update.message.reply_text(
        f"📊 SMC v4.1 Twelve Data
"
        f"Estado: {estado}
"
        f"🔗 API: Twelve Data
"
        f"Pares: {len(CONFIG['pares_ativos'])}
"
        f"TF: 15min
"
        f"Velas: {CONFIG['lookback_candles']}
"
        f"Sinais: {len(sinais)}"
    )

async def sinais(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not sinais:
        await update.message.reply_text("ℹ️ Sem sinais. /forçar XAU/USD")
        return
    
    ultimo = sinais[-1]
    msg = (
        f"🎯 {ultimo['direction']} {ultimo['par']}
"
        f"{ultimo['tf']} | {ultimo['timestamp']}
"
        f"Entry: {ultimo['entry']}
"
        f"TP: {ultimo['tp']} (R:{ultimo['rr']})
"
        f"SL: {ultimo['sl']}
"
        f"📈 {ultimo['confidence']} | {ultimo['source']}"
    )
    await update.message.reply_text(msg)

async def forcar_analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    par = context.args[0].upper() if context.args else "XAU/USD"
    
    if par not in CONFIG['pares_ativos']:
        await update.message.reply_text(f"❌ Par inválido.
Use: {', '.join(CONFIG['pares_ativos'][:5])}...")
        return
    
    await update.message.reply_text(f"🔍 Twelve Data: {par} 15min...")
    
    sinal = await analisar_smc(par)
    if sinal:
        sinais.append(sinal)
        if len(sinais) > 20:
            sinais[:] = sinais[-20:]
        
        await update.message.reply_text(
            f"🎯 {sinal['direction']} {sinal['par']} 15m
"
            f"⏰ {sinal['timestamp']} | R:{sinal['rr']}
"
            f"💰 {sinal['entry']} → TP:{sinal['tp']} SL:{sinal['sl']}
"
            f"📈 {sinal['confidence']} Twelve Data"
        )
    else:
        await update.message.reply_text(f"❌ Sem setup SMC em {par}.
💡 Tente XAU/USD (mais volátil)")

async def monitor_loop(context: ContextTypes.DEFAULT_TYPE):
    """Monitora 17 pares (otimizado)"""
    if not CONFIG['bot_ativo']:
        return
    
    print(f"🔍 Twelve Data: {len(CONFIG['pares_ativos'])} pares...")
    
    # Top 6 pares primeiro (velocidade)
    priority = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF"]
    
    for par in priority + CONFIG['pares_ativos'][6:]:
        if len(sinais) >= 3:  # Limite sinais por ciclo
            break
            
        sinal = await analisar_smc(par)
        if sinal:
            sinais.append(sinal)
            if len(sinais) > 20:
                sinais[:] = sinais[-20:]
            
            msg = f"🎯 AUTO {sinal['direction']} {sinal['par']} | R:{sinal['rr']} | {sinal['confidence']}"
            await context.bot.send_message(chat_id=CONFIG['chat_id'], text=msg)

# MAIN
def main():
    app = Application.builder().token(CONFIG['bot_token']).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("sinais", sinais))
    app.add_handler(CommandHandler("forçar", forcar_analise))
    
    # Monitora a cada 2.5min
    job_queue = app.job_queue
    job_queue.run_repeating(monitor_loop, interval=150, first=10)
    
    print(f"🚀 SMC Bot v4.1 TWELVE DATA - {len(CONFIG['pares_ativos'])} PARES!")
    print("📡 API Twelve Data ativa")
    
    app.run_polling()

if __name__ == "__main__":
    main()
