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

# URLs que FUNCIONAM com a API DexScreener
CHAINS = {
    "ethereum": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0x2170ed0880ac9a755fd29b2688956bd959f933f8",  # ETH
        "explorer": "https://etherscan.io/token/",
        "enabled": True
    },
    "bsc": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # BNB
        "explorer": "https://bscscan.com/token/",
        "enabled": True
    },
    "polygon": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270",  # MATIC
        "explorer": "https://polygonscan.com/token/",
        "enabled": True
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
            logging.error(f"Erro Telegram {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"Erro Telegram: {e}")
        return False

def get_token_pairs(chain):
    """Busca pares de um token específico (URL que FUNCIONA)"""
    if not CHAINS[chain]["enabled"]:
        return []
    
    try:
        response = requests.get(CHAINS[chain]["url"], timeout=15)
        if response.status_code == 200:
            data = response.json()
            pairs = data.get("pairs", [])
            logging.info(f"✅ {chain}: {len(pairs)} pares encontrados")
            return pairs
        else:
            logging.error(f"❌ {chain}: API retornou {response.status_code}")
            logging.error(f"URL: {CHAINS[chain]['url']}")
            return []
    except Exception as e:
        logging.error(f"❌ Erro em {chain}: {e}")
        return []

def filter_recent_tokens(pairs, max_hours=24):
    """Filtra tokens recentes"""
    recent_tokens = []
    
    for pair in pairs:
        try:
            created_at = pair.get("pairCreatedAt")
            if not created_at:
                continue
                
            # Converter timestamp para datetime
            created_time = datetime.fromtimestamp(created_at / 1000)
            age = datetime.now() - created_time
            
            # Verificar se é recente
            if age < timedelta(hours=max_hours):
                recent_tokens.append(pair)
                
        except Exception as e:
            continue
    
    return recent_tokens

def analyze_token(pair, chain):
    """Analisa um token"""
    base_token = pair.get("baseToken", {})
    
    token_address = base_token.get("address")
    token_name = base_token.get("name", "Unknown")[:25]
    token_symbol = base_token.get("symbol", "UNKNOWN")
    
    liquidity = pair.get("liquidity", {}).get("usd", 0)
    volume_24h = pair.get("volume", {}).get("h24", 0)
    price = pair.get("priceUsd", "0")
    created_at = pair.get("pairCreatedAt")
    
    # Calcular idade
    age_str = "Desconhecida"
    age_hours = 999
    if created_at:
        try:
            created_time = datetime.fromtimestamp(created_at / 1000)
            age = datetime.now() - created_time
            age_hours = age.total_seconds() / 3600
            age_str = f"{age_hours:.1f}h"
        except:
            pass
    
    # Score baseado em vários fatores
    score = 0
    details = []
    
    # Idade (quanto mais novo, melhor)
    if age_hours < 6:
        score += 2
        details.append(f"🆕 {age_str}")
    elif age_hours < 12:
        score += 1
        details.append(f"⏰ {age_str}")
    
    # Liquidez
    if liquidity > 10000:
        score += 2
        details.append(f"💰 ${liquidity:,.0f}")
    elif liquidity > 5000:
        score += 1
        details.append(f"💧 ${liquidity:,.0f}")
    
    # Volume
    if volume_24h > 50000:
        score += 2
        details.append(f"📈 ${volume_24h:,.0f}")
    elif volume_24h > 20000:
        score += 1
        details.append(f"📊 ${volume_24h:,.0f}")
    
    return {
        "address": token_address,
        "name": token_name,
        "symbol": token_symbol,
        "price": price,
        "liquidity": liquidity,
        "volume": volume_24h,
        "age_hours": age_hours,
        "score": score,
        "details": details,
        "url": pair.get("url", ""),
        "dex": pair.get("dexId", ""),
        "explorer": f"{CHAINS[chain]['explorer']}{token_address}"
    }

def create_message(analysis, chain):
    """Cria mensagem para Telegram"""
    emoji = "🚀" if analysis["score"] >= 4 else "⭐" if analysis["score"] >= 2 else "🔍"
    
    message = f"{emoji} <b>TOKEN {chain.upper()}</b>\n\n"
    message += f"<b>{analysis['name']} ({analysis['symbol']})</b>\n"
    message += f"💵 <b>Preço:</b> ${analysis['price']}\n"
    message += f"⭐ <b>Score:</b> {analysis['score']}/6\n\n"
    
    message += "<b>📊 Análise:</b>\n"
    for detail in analysis["details"]:
        message += f"• {detail}\n"
    
    message += f"\n<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis['url']}'>DexScreener</a>\n"
    message += f"• <a href='{analysis['explorer']}'>Explorer</a>"
    
    return message

def monitor_tokens():
    """Monitora tokens"""
    logging.info("🔍 Procurando tokens...")
    tokens_encontrados = 0
    
    for chain in CHAINS:
        if not CHAINS[chain]["enabled"]:
            continue
            
        try:
            # Buscar pares do token base
            all_pairs = get_token_pairs(chain)
            
            if not all_pairs:
                continue
            
            # Filtrar apenas os recentes
            recent_pairs = filter_recent_tokens(all_pairs, max_hours=24)
            
            logging.info(f"📊 {chain}: {len(recent_pairs)} tokens recentes")
            
            for pair in recent_pairs:
                token_address = pair.get("baseToken", {}).get("address")
                
                if token_address and token_address not in vistos:
                    vistos.add(token_address)
                    
                    analysis = analyze_token(pair, chain)
                    
                    # Notificar tokens interessantes
                    if analysis["score"] >= 2:
                        message = create_message(analysis, chain)
                        if send_telegram(message):
                            tokens_encontrados += 1
                            logging.info(f"✅ {chain}: {analysis['symbol']} (Score: {analysis['score']})")
                        time.sleep(1)
                    
        except Exception as e:
            logging.error(f"Erro em {chain}: {e}")
    
    return tokens_encontrados

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    logging.info("🤖 Bot iniciado! Monitorando tokens...")
    
    # Testar conexão com Telegram
    if send_telegram("🤖 <b>Bot iniciado!</b>\n🔍 Monitorando tokens..."):
        logging.info("✅ Conexão com Telegram OK!")
    else:
        logging.error("❌ Falha na conexão com Telegram!")
        return
    
    # Loop principal
    while True:
        try:
            tokens_encontrados = monitor_tokens()
            
            if tokens_encontrados > 0:
                logging.info(f"🎉 {tokens_encontrados} tokens encontrados!")
            else:
                logging.info("⏭ Nenhum token novo encontrado")
            
            # Esperar tempo aleatório entre 10-15 minutos
            wait_time = random.randint(600, 900)
            logging.info(f"⏳ Próxima verificação em {wait_time//60} minutos...")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
