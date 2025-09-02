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

# URLs corretas da API DexScreener (versão mais recente)
CHAINS = {
    "ethereum": {
        "url": "https://api.dexscreener.com/latest/dex/networks/ethereum/pairs",
        "explorer": "https://etherscan.io/token/",
        "enabled": True
    },
    "bsc": {
        "url": "https://api.dexscreener.com/latest/dex/networks/bsc/pairs", 
        "explorer": "https://bscscan.com/token/",
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
            logging.error(f"Erro Telegram {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logging.error(f"Erro Telegram: {e}")
        return False

def get_all_pairs(chain):
    """Busca todos os pares de uma chain usando API correta"""
    if not CHAINS[chain]["enabled"]:
        return []
    
    try:
        response = requests.get(CHAINS[chain]["url"], timeout=15)
        if response.status_code == 200:
            data = response.json()
            # A nova API retorna a lista diretamente
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

def filter_recent_tokens(pairs, max_hours=6):
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
            
            # Verificar se é recente (menos de max_hours)
            if age < timedelta(hours=max_hours):
                recent_tokens.append(pair)
                
        except Exception as e:
            continue  # Ignorar erros individuais
    
    return recent_tokens

def analyze_token(pair, chain):
    """Analisa um token"""
    base_token = pair.get("baseToken", {})
    
    token_address = base_token.get("address")
    token_name = base_token.get("name", "Unknown")[:30]
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
            if age_hours < 1:
                age_str = f"{age_hours*60:.0f}min"
            else:
                age_str = f"{age_hours:.1f}h"
        except:
            pass
    
    # Score baseado em vários fatores
    score = 0
    details = []
    
    # Idade (quanto mais novo, melhor)
    if age_hours < 1:
        score += 3
        details.append(f"🆕 {age_str}")
    elif age_hours < 3:
        score += 2
        details.append(f"⏰ {age_str}")
    elif age_hours < 6:
        score += 1
        details.append(f"📅 {age_str}")
    
    # Liquidez
    if liquidity > 50000:
        score += 3
        details.append(f"💰 ${liquidity:,.0f}")
    elif liquidity > 20000:
        score += 2
        details.append(f"💧 ${liquidity:,.0f}")
    elif liquidity > 5000:
        score += 1
        details.append(f"💦 ${liquidity:,.0f}")
    
    # Volume
    if volume_24h > 100000:
        score += 2
        details.append(f"📈 ${volume_24h:,.0f}")
    elif volume_24h > 50000:
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
    emoji = "🚀" if analysis["score"] >= 5 else "⭐" if analysis["score"] >= 3 else "🔍"
    
    message = f"{emoji} <b>NOVO TOKEN {chain.upper()}</b>\n\n"
    message += f"<b>{analysis['name']} ({analysis['symbol']})</b>\n"
    message += f"💵 <b>Preço:</b> ${analysis['price']}\n"
    message += f"⭐ <b>Score:</b> {analysis['score']}/8\n\n"
    
    message += "<b>📊 Análise:</b>\n"
    for detail in analysis["details"]:
        message += f"• {detail}\n"
    
    message += f"\n<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis['url']}'>DexScreener</a>\n"
    message += f"• <a href='{analysis['explorer']}'>Explorer</a>"
    
    return message

def monitor_tokens():
    """Monitora tokens"""
    logging.info("🔍 Procurando tokens recentes...")
    tokens_encontrados = 0
    
    for chain in CHAINS:
        if not CHAINS[chain]["enabled"]:
            continue
            
        try:
            # Buscar todos os pares
            all_pairs = get_all_pairs(chain)
            
            if not all_pairs:
                continue
            
            # Filtrar apenas os recentes (últimas 6 horas)
            recent_pairs = filter_recent_tokens(all_pairs, max_hours=6)
            
            logging.info(f"📊 {chain}: {len(recent_pairs)} tokens recentes")
            
            for pair in recent_pairs:
                token_address = pair.get("baseToken", {}).get("address")
                
                if token_address and token_address not in vistos:
                    vistos.add(token_address)
                    
                    analysis = analyze_token(pair, chain)
                    
                    # Notificar tokens promissores (score >= 3)
                    if analysis["score"] >= 3:
                        message = create_message(analysis, chain)
                        if send_telegram(message):
                            tokens_encontrados += 1
                            logging.info(f"✅ {chain}: {analysis['symbol']} (Score: {analysis['score']})")
                        time.sleep(1)  # Evitar spam
                    
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
    if send_telegram("🤖 <b>Bot iniciado!</b>\n🔍 Monitorando tokens novos..."):
        logging.info("✅ Conexão com Telegram OK!")
    else:
        logging.error("❌ Falha na conexão com Telegram!")
        return
    
    # Loop principal
    while True:
        try:
            tokens_encontrados = monitor_tokens()
            
            if tokens_encontrados > 0:
                logging.info(f"🎉 {tokens_encontrados} novos tokens encontrados!")
            else:
                logging.info("⏭ Nenhum token novo encontrado")
            
            # Esperar tempo aleatório entre 5-8 minutos
            wait_time = random.randint(300, 480)
            logging.info(f"⏳ Próxima verificação em {wait_time//60} minutos...")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
