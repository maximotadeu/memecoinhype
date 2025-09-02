import os
import requests
import time
import logging
import random
from datetime import datetime, timedelta

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Configurações
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

# Para buscar tokens NOVOS de verdade
CHAINS = {
    "ethereum": {
        "url": "https://api.dexscreener.com/latest/dex/search/?q=0x&limit=20",
        "explorer": "https://etherscan.io/token/"
    },
    "bsc": {
        "url": "https://api.dexscreener.com/latest/dex/search/?q=0x&limit=20",
        "explorer": "https://bscscan.com/token/"
    },
    "base": {
        "url": "https://api.dexscreener.com/latest/dex/search/?q=0x&limit=20",
        "explorer": "https://basescan.org/token/"
    },
    "arbitrum": {
        "url": "https://api.dexscreener.com/latest/dex/search/?q=0x&limit=20",
        "explorer": "https://arbiscan.io/token/"
    }
}

# Para armazenar tokens já vistos
vistos = set()

def send_telegram(message):
    """Envia mensagem para o Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Token ou Chat ID não configurado!")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            logging.error(f"Erro Telegram: {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"Erro: {e}")
        return False

def get_recent_tokens(chain):
    """Busca tokens RECÉM-CRIADOS"""
    try:
        url = CHAINS[chain]["url"]
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        pairs = data.get("pairs", [])
        
        # Filtrar apenas tokens criados nas últimas 2 horas
        recent_tokens = []
        for pair in pairs:
            created_at = pair.get("pairCreatedAt")
            if created_at:
                created_time = datetime.fromtimestamp(created_at / 1000)
                if datetime.now() - created_time < timedelta(hours=2):
                    recent_tokens.append(pair)
        
        return recent_tokens[:10]  # Limitar a 10 tokens
        
    except Exception as e:
        logging.error(f"Erro ao buscar tokens {chain}: {e}")
        return []

def analyze_token(pair, chain):
    """Analisa um token"""
    base_token = pair.get("baseToken", {})
    
    token_address = base_token.get("address")
    token_name = base_token.get("name", "Unknown")
    token_symbol = base_token.get("symbol", "UNKNOWN")
    
    liquidity = pair.get("liquidity", {}).get("usd", 0)
    volume_24h = pair.get("volume", {}).get("h24", 0)
    created_at = pair.get("pairCreatedAt")
    
    # Calcular idade
    if created_at:
        created_time = datetime.fromtimestamp(created_at / 1000)
        age = datetime.now() - created_time
        age_minutes = age.total_seconds() / 60
    else:
        age_minutes = 9999
    
    # Score baseado em vários fatores
    score = 0
    details = []
    
    # Idade (quanto mais novo, melhor)
    if age_minutes < 30:
        score += 3
        details.append(f"🆕 Muito novo: {age_minutes:.0f}min")
    elif age_minutes < 120:
        score += 2
        details.append(f"⏰ Novo: {age_minutes:.0f}min")
    else:
        details.append(f"⏳ Idade: {age_minutes:.0f}min")
    
    # Liquidez
    if liquidity > 50000:
        score += 3
        details.append(f"💰 Liquidez: ${liquidity:,.0f}")
    elif liquidity > 20000:
        score += 2
        details.append(f"💧 Liquidez: ${liquidity:,.0f}")
    elif liquidity > 5000:
        score += 1
        details.append(f"💦 Liquidez: ${liquidity:,.0f}")
    else:
        details.append(f"🌵 Liquidez: ${liquidity:,.0f}")
    
    # Volume
    if volume_24h > 100000:
        score += 2
        details.append(f"📈 Volume: ${volume_24h:,.0f}")
    elif volume_24h > 50000:
        score += 1
        details.append(f"📊 Volume: ${volume_24h:,.0f}")
    else:
        details.append(f"📉 Volume: ${volume_24h:,.0f}")
    
    return {
        "address": token_address,
        "name": token_name,
        "symbol": token_symbol,
        "liquidity": liquidity,
        "volume": volume_24h,
        "age_minutes": age_minutes,
        "score": score,
        "details": details,
        "url": pair.get("url", ""),
        "dex": pair.get("dexId", ""),
        "explorer": f"{CHAINS[chain]['explorer']}{token_address}"
    }

def create_message(analysis, chain):
    """Cria mensagem para Telegram"""
    emoji = "🚀" if analysis["score"] >= 5 else "⭐" if analysis["score"] >= 3 else "🔍"
    
    message = f"{emoji} <b>NOVO TOKEN {chain.upper()}</b>\n\n"
    message += f"<b>{analysis['name']} ({analysis['symbol']})</b>\n"
    message += f"⭐ <b>Score:</b> {analysis['score']}/8\n\n"
    
    message += "<b>📊 Estatísticas:</b>\n"
    for detail in analysis["details"]:
        message += f"• {detail}\n"
    
    message += f"\n<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis['url']}'>DexScreener</a>\n"
    message += f"• <a href='{analysis['explorer']}'>Explorer</a>\n"
    message += f"• <b>DEX:</b> {analysis['dex']}"
    
    return message

def monitor_new_tokens():
    """Monitora tokens NOVOS de verdade"""
    logging.info("🔍 Procurando tokens NOVOS...")
    
    for chain in CHAINS.keys():
        try:
            tokens = get_recent_tokens(chain)
            logging.info(f"📊 {chain}: {len(tokens)} tokens recentes")
            
            for token in tokens:
                token_address = token.get("baseToken", {}).get("address")
                
                if token_address and token_address not in vistos:
                    vistos.add(token_address)
                    
                    analysis = analyze_token(token, chain)
                    
                    # Só notificar se for promissor
                    if analysis["score"] >= 4 and analysis["age_minutes"] < 120:
                        message = create_message(analysis, chain)
                        if send_telegram(message):
                            logging.info(f"✅ Novo token {chain}: {analysis['symbol']}")
                        time.sleep(1)  # Evitar spam
                    
        except Exception as e:
            logging.error(f"Erro em {chain}: {e}")

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    logging.info("🤖 Bot iniciado! Procurando tokens NOVOS...")
    send_telegram("🤖 <b>Bot iniciado!</b>\n🔍 Procurando tokens novos...")
    
    # Loop principal
    while True:
        try:
            monitor_new_tokens()
            # Esperar tempo aleatório entre 2-5 minutos
            wait_time = random.randint(120, 300)
            logging.info(f"⏳ Próxima verificação em {wait_time} segundos...")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
