import os
import requests
import time
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Configurações
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
CHAINS = ["ethereum", "bsc"]
HONEYPOT_API = "https://api.honeypot.is/v2/IsHoneypot"

# Variável global para armazenar pares vistos
vistos = set()

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem Telegram: {e}")

def get_new_pairs(chain):
    url = f"https://api.dexscreener.com/latest/dex/pairs/{chain}"
    try:
        r = requests.get(url, timeout=15)
        return r.json().get("pairs", [])
    except Exception as e:
        logging.error(f"Erro Dex {chain}: {e}")
        return []

def score_liquidity(liq):
    if liq > 100000: return 30
    if liq > 50000: return 20
    if liq > 20000: return 10
    return 0

def score_volume(vol):
    if vol > 200000: return 20
    if vol > 100000: return 15
    if vol > 50000: return 10
    return 0

def check_honeypot(chain, contract):
    try:
        url = f"{HONEYPOT_API}?chain={chain}&token={contract}"
        r = requests.get(url, timeout=15).json()
        sim = r.get("simulation", {})
        if sim.get("isHoneypot", False):
            return 0
        buy_tax = sim.get("buyTax", 0)
        sell_tax = sim.get("sellTax", 0)
        if buy_tax < 10 and sell_tax < 10:
            return 20
        if buy_tax < 20 and sell_tax < 20:
            return 10
        return 0
    except Exception as e:
        logging.error(f"Erro Honeypot {contract}: {e}")
        return 0

def check_holders(chain, contract):
    # Implementação simplificada - você pode adicionar API de explorers depois
    return 15

def check_lp_lock(chain, contract):
    # Implementação simplificada
    return 5

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('🤖 Bot de Monitoramento de Tokens Ativo!')
    await update.message.reply_text('🔍 Monitorando novos tokens nas redes...')

async def check_tokens(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Verificando novos tokens...")
    for chain in CHAINS:
        pares = get_new_pairs(chain)
        for p in pares:
            pair_addr = p.get("pairAddress")
            if pair_addr and pair_addr not in vistos:
                vistos.add(pair_addr)
                base_token = p.get("baseToken", {})
                token_name = base_token.get("name", "N/A")
                token_symbol = base_token.get("symbol", "N/A")
                contract = base_token.get("address", "")
                liquidity = p.get("liquidity", {}).get("usd", 0)
                volume24h = p.get("volume", {}).get("h24", 0)
                url = p.get("url", "")

                # Score
                score = 0
                score += score_liquidity(liquidity)
                score += score_volume(volume24h)
                score += check_holders(chain, contract)
                score += check_lp_lock(chain, contract)
                score += check_honeypot(chain, contract)

                if score >= 50:
                    msg = (
                        f"🚀 <b>Novo Token em {chain.upper()}!</b>\n\n"
                        f"<b>{token_name}</b> ({token_symbol})\n"
                        f"💧 <b>Liquidez:</b> ${liquidity:,.0f}\n"
                        f"📈 <b>Volume 24h:</b> ${volume24h:,.0f}\n"
                        f"⭐ <b>Score de Risco:</b> {score}/100\n"
                        f"🔗 <a href='{url}'>DexScreener</a>"
                    )
                    logging.info(f"Novo token encontrado: {token_symbol} (Score: {score})")
                    send_telegram(msg)
                else:
                    logging.info(f"Token {token_symbol} ignorado (score {score})")

def main():
    # Verificar se as variáveis de ambiente estão configuradas
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Variáveis de ambiente TELEGRAM_TOKEN e CHAT_ID são necessárias!")
        return
    
    # Criar aplicação do Telegram
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Adicionar handlers
    application.add_handler(CommandHandler("start", start))
    
    # Configurar job para verificar tokens a cada minuto
    job_queue = application.job_queue
    job_queue.run_repeating(check_tokens, interval=60, first=10)
    
    # Iniciar o bot
    application.run_polling()

if __name__ == "__main__":
    main()
