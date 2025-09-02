import os
import requests
import time
import logging
from datetime import datetime, timedelta

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Configurações
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

# URLs corretas para buscar NOVOS tokens
CHAINS = {
    "ethereum": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/",
        "new_tokens": [
            "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984",  # UNI (exemplo)
            "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0",  # MATIC
            "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce"   # SHIB
        ]
    },
    "bsc": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/",
        "new_tokens": [
            "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82",  # CAKE
            "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
            "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c"   # BTCB
        ]
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
            logging.info("✅ Mensagem enviada!")
            return True
        else:
            logging.error(f"❌ Erro {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logging.error(f"❌ Erro: {e}")
        return False

def get_new_pairs(chain, token_address):
    """Busca pares de um token específico"""
    try:
        url = f"{CHAINS[chain]['url']}{token_address}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        pairs = data.get("pairs", [])
        
        # Filtrar apenas pares criados nas últimas 24 horas
        recent_pairs = []
        for pair in pairs:
            created_at = pair.get("pairCreatedAt")
            if created_at:
                # Converter timestamp para datetime
                created_time = datetime.fromtimestamp(created_at / 1000)
                if datetime.now() - created_time < timedelta(hours=24):
                    recent_pairs.append(pair)
        
        return recent_pairs
        
    except Exception as e:
        logging.error(f"❌ Erro ao buscar pares {chain}: {e}")
        return []

def analyze_token(pair, chain):
    """Analisa um token"""
    base_token = pair.get("baseToken", {})
    quote_token = pair.get("quoteToken", {})
    
    token_address = base_token.get("address")
    token_name = base_token.get("name", "Unknown")
    token_symbol = base_token.get("symbol", "UNKNOWN")
    token_price = pair.get("priceUsd", "0")
    
    liquidity = pair.get("liquidity", {}).get("usd", 0)
    volume_24h = pair.get("volume", {}).get("h24", 0)
    created_at = pair.get("pairCreatedAt")
    
    # Calcular idade do par
    if created_at:
        created_time = datetime.fromtimestamp(created_at / 1000)
        age = datetime.now() - created_time
        age_hours = age.total_seconds() / 3600
    else:
        age_hours = 999
    
    # Score baseado em liquidez, volume e idade
    score = 0
    details = []
    
    if liquidity > 10000:
        score += 2
        details.append(f"💰 Liquidez: ${liquidity:,.0f}")
    else:
        details.append(f"💧 Liquidez baixa: ${liquidity:,.0f}")
    
    if volume_24h > 50000:
        score += 2
        details.append(f"📈 Volume: ${volume_24h:,.0f}")
    else:
        details.append(f"📊 Volume: ${volume_24h:,.0f}")
    
    if age_hours < 6:
        score += 3
        details.append(f"🆕 Novo: {age_hours:.1f}h")
    elif age_hours < 24:
        score += 1
        details.append(f"⏰ Recente: {age_hours:.1f}h")
    else:
        details.append(f"⏳ Antigo: {age_hours:.1f}h")
    
    return {
        "address": token_address,
        "name": token_name,
        "symbol": token_symbol,
        "price": token_price,
        "liquidity": liquidity,
        "volume": volume_24h,
        "age_hours": age_hours,
        "score": score,
        "details": details,
        "url": pair.get("url", ""),
        "dex": pair.get("dexId", "")
    }

def monitor_tokens():
    """Monitora tokens em todas as chains"""
    logging.info("🔍 Procurando novos tokens...")
    
    for chain, config in CHAINS.items():
        for token_address in config["new_tokens"]:
            try:
                pairs = get_new_pairs(chain, token_address)
                
                for pair in pairs:
                    pair_address = pair.get("pairAddress")
                    
                    if pair_address and pair_address not in vistos:
                        vistos.add(pair_address)
                        
                        analysis = analyze_token(pair, chain)
                        
                        # Só notificar se for relevante
                        if analysis["score"] >= 3 and analysis["age_hours"] < 24:
                            message = create_message(analysis, chain)
                            send_telegram(message)
                            logging.info(f"✅ Novo token: {analysis['symbol']}")
                            
            except Exception as e:
                logging.error(f"❌ Erro em {chain}: {e}")

def create_message(analysis, chain):
    """Cria mensagem para Telegram"""
    message = f"🚀 <b>NOVO TOKEN {chain.upper()}</b>\n\n"
    message += f"<b>{analysis['name']} ({analysis['symbol']})</b>\n"
    message += f"💵 <b>Preço:</b> ${analysis['price']}\n"
    message += f"⭐ <b>Score:</b> {analysis['score']}/7\n\n"
    
    message += "<b>📊 Detalhes:</b>\n"
    for detail in analysis["details"]:
        message += f"• {detail}\n"
    
    message += f"\n<b>🔗 DexScreener:</b>\n"
    message += f"<a href='{analysis['url']}'>Ver par</a>\n"
    message += f"<b>🏦 DEX:</b> {analysis['dex']}"
    
    return message

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("❌ Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    # Testar conexão
    if not send_telegram("🤖 Bot iniciado! Procurando novos tokens..."):
        logging.error("❌ Falha no Telegram!")
        return
    
    logging.info("✅ Bot funcionando! Iniciando monitoramento...")
    
    # Loop principal
    while True:
        try:
            monitor_tokens()
            time.sleep(300)  # Verificar a cada 5 minutos
            
        except Exception as e:
            logging.error(f"❌ Erro no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
