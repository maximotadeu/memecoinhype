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

# URLs para buscar tokens NOVOS de verdade
CHAINS = {
    "ethereum": {
        "urls": [
            "https://api.dexscreener.com/latest/dex/pairs/ethereum?sort=createdAt&order=desc",
            "https://api.dexscreener.com/latest/dex/pairs/ethereum?sort=volume&order=desc"
        ],
        "explorer": "https://etherscan.io/token/"
    },
    "bsc": {
        "urls": [
            "https://api.dexscreener.com/latest/dex/pairs/bsc?sort=createdAt&order=desc",
            "https://api.dexscreener.com/latest/dex/pairs/bsc?sort=volume&order=desc"
        ],
        "explorer": "https://bscscan.com/token/"
    },
    "polygon": {
        "urls": [
            "https://api.dexscreener.com/latest/dex/pairs/polygon?sort=createdAt&order=desc"
        ],
        "explorer": "https://polygonscan.com/token/"
    },
    "arbitrum": {
        "urls": [
            "https://api.dexscreener.com/latest/dex/pairs/arbitrum?sort=createdAt&order=desc"
        ],
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
        return response.status_code == 200
    except Exception as e:
        logging.error(f"Erro Telegram: {e}")
        return False

def get_recent_pairs(chain):
    """Busca pares RECÉM-CRIADOS"""
    all_pairs = []
    
    for url in CHAINS[chain]["urls"]:
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            pairs = data.get("pairs", [])
            all_pairs.extend(pairs)
            
            logging.info(f"📊 {chain}: {len(pairs)} pares encontrados")
            
        except Exception as e:
            logging.error(f"Erro ao buscar {chain}: {e}")
    
    # Remover duplicatas
    unique_pairs = {}
    for pair in all_pairs:
        pair_address = pair.get("pairAddress")
        if pair_address:
            unique_pairs[pair_address] = pair
    
    return list(unique_pairs.values())

def filter_recent_tokens(pairs, max_age_hours=6):
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
            if age < timedelta(hours=max_age_hours):
                recent_tokens.append(pair)
                
        except Exception as e:
            logging.error(f"Erro ao processar par: {e}")
    
    return recent_tokens

def analyze_token(pair, chain):
    """Analisa um token"""
    base_token = pair.get("baseToken", {})
    quote_token = pair.get("quoteToken", {})
    
    token_address = base_token.get("address")
    token_name = base_token.get("name", "Unknown").replace('\n', ' ').replace('\r', ' ')
    token_symbol = base_token.get("symbol", "UNKNOWN")
    
    liquidity = pair.get("liquidity", {}).get("usd", 0)
    volume_24h = pair.get("volume", {}).get("h24", 0)
    price = pair.get("priceUsd", "0")
    price_change = pair.get("priceChange", {}).get("h24", 0)
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
    if age_hours < 1:
        score += 3
        details.append(f"🆕 Muito novo: {age_str}")
    elif age_hours < 6:
        score += 2
        details.append(f"⏰ Novo: {age_str}")
    else:
        details.append(f"⏳ Idade: {age_str}")
    
    # Liquidez
    if liquidity > 100000:
        score += 3
        details.append(f"💰 Liquidez alta: ${liquidity:,.0f}")
    elif liquidity > 50000:
        score += 2
        details.append(f"💧 Liquidez boa: ${liquidity:,.0f}")
    elif liquidity > 20000:
        score += 1
        details.append(f"💦 Liquidez moderada: ${liquidity:,.0f}")
    else:
        details.append(f"🌵 Liquidez baixa: ${liquidity:,.0f}")
    
    # Volume
    if volume_24h > 200000:
        score += 3
        details.append(f"📈 Volume alto: ${volume_24h:,.0f}")
    elif volume_24h > 100000:
        score += 2
        details.append(f"📊 Volume bom: ${volume_24h:,.0f}")
    elif volume_24h > 50000:
        score += 1
        details.append(f"📉 Volume moderado: ${volume_24h:,.0f}")
    else:
        details.append(f"📉 Volume baixo: ${volume_24h:,.0f}")
    
    # Variação de preço
    if price_change > 20:
        score += 2
        details.append(f"🚀 Alta: +{price_change:.1f}%")
    elif price_change > 10:
        score += 1
        details.append(f"📈 Subindo: +{price_change:.1f}%")
    elif price_change < -10:
        score -= 1
        details.append(f"📉 Caindo: {price_change:.1f}%")
    
    return {
        "address": token_address,
        "name": token_name,
        "symbol": token_symbol,
        "price": price,
        "liquidity": liquidity,
        "volume": volume_24h,
        "price_change": price_change,
        "age_hours": age_hours,
        "score": score,
        "details": details,
        "url": pair.get("url", ""),
        "dex": pair.get("dexId", ""),
        "explorer": f"{CHAINS[chain]['explorer']}{token_address}"
    }

def create_message(analysis, chain):
    """Cria mensagem para Telegram"""
    emoji = "🚀" if analysis["score"] >= 6 else "⭐" if analysis["score"] >= 4 else "🔍"
    
    message = f"{emoji} <b>NOVO TOKEN {chain.upper()}</b>\n\n"
    message += f"<b>{analysis['name']} ({analysis['symbol']})</b>\n"
    message += f"💵 <b>Preço:</b> ${analysis['price']}\n"
    message += f"⭐ <b>Score:</b> {analysis['score']}/10\n\n"
    
    message += "<b>📊 Estatísticas:</b>\n"
    for detail in analysis["details"]:
        message += f"• {detail}\n"
    
    message += f"\n<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis['url']}'>DexScreener</a>\n"
    message += f"• <a href='{analysis['explorer']}'>Explorer</a>\n"
    message += f"• <b>DEX:</b> {analysis['dex']}"
    
    return message

def monitor_tokens():
    """Monitora tokens"""
    logging.info("🔍 Procurando tokens...")
    
    for chain in CHAINS.keys():
        try:
            # Buscar todos os pares
            all_pairs = get_recent_pairs(chain)
            
            # Filtrar apenas os recentes
            recent_pairs = filter_recent_tokens(all_pairs, max_age_hours=12)
            
            logging.info(f"📊 {chain}: {len(recent_pairs)} tokens recentes")
            
            for pair in recent_pairs:
                token_address = pair.get("baseToken", {}).get("address")
                
                if token_address and token_address not in vistos:
                    vistos.add(token_address)
                    
                    analysis = analyze_token(pair, chain)
                    
                    # Notificar tokens promissores
                    if analysis["score"] >= 4:
                        message = create_message(analysis, chain)
                        if send_telegram(message):
                            logging.info(f"✅ Token {chain}: {analysis['symbol']} (Score: {analysis['score']})")
                        time.sleep(1)  # Evitar spam
                    
        except Exception as e:
            logging.error(f"Erro em {chain}: {e}")

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    logging.info("🤖 Bot iniciado! Procurando tokens...")
    send_telegram("🤖 <b>Bot iniciado!</b>\n🔍 Monitorando tokens novos...")
    
    # Loop principal
    while True:
        try:
            monitor_tokens()
            # Esperar tempo aleatório entre 3-7 minutos
            wait_time = random.randint(180, 420)
            logging.info(f"⏳ Próxima verificação em {wait_time//60} minutos...")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
