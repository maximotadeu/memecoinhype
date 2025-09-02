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

# JANELA TEMPORAL AMPLIADA - Perfect for memecoins!
MAX_AGE_DAYS = 7  # Até 7 dias (168 horas)
MIN_AGE_HOURS = 2  # Mínimo 2 horas

# APIs de segurança
HONEYPOT_CHECK_API = "https://api.honeypot.is/v2/IsHoneypot"

# Chains suportadas
CHAINS = {
    "ethereum": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0x2170ed0880ac9a755fd29b2688956bd959f933f8",
        "explorer": "https://etherscan.io/token/",
        "chain_id": "eth",
        "native_token": "ETH",
        "enabled": True,
        "max_age_days": 5
    },
    "bsc": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
        "explorer": "https://bscscan.com/token/", 
        "chain_id": "bsc",
        "native_token": "BNB",
        "enabled": True,
        "max_age_days": 7
    },
    "solana": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112",
        "explorer": "https://solscan.io/token/",
        "chain_id": "sol",
        "native_token": "SOL",
        "enabled": True,
        "max_age_days": 3
    }
}

# DEXs confiáveis
RELIABLE_DEXS = {
    "ethereum": ["uniswap", "sushiswap"],
    "bsc": ["pancakeswap", "biswap"],
    "solana": ["raydium", "orca"]
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

def get_token_pairs(chain):
    """Busca pares de um token específico"""
    try:
        response = requests.get(CHAINS[chain]["url"], timeout=15)
        if response.status_code == 200:
            data = response.json()
            pairs = data.get("pairs", [])
            
            # Ordenar por volume (mais populares primeiro)
            pairs.sort(key=lambda x: x.get("volume", {}).get("h24", 0), reverse=True)
            
            logging.info(f"✅ {chain}: {len(pairs)} pares encontrados")
            return pairs[:20]
            
        return []
    except Exception as e:
        logging.error(f"❌ Erro em {chain}: {e}")
        return []

def check_honeypot(chain, token_address):
    """Verifica se é honeypot"""
    if chain not in ["eth", "bsc"]:
        return True, 0, 0, "🔓 Rede não suportada"
    
    try:
        url = f"{HONEYPOT_CHECK_API}?chain={chain}&token={token_address}"
        response = requests.get(url, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            simulation = data.get("simulation", {})
            
            is_honeypot = simulation.get("isHoneypot", False)
            buy_tax = simulation.get("buyTax", 0)
            sell_tax = simulation.get("sellTax", 0)
            
            status = "✅ Sem honeypot" if not is_honeypot else "🚫 HONEYPOT"
            return not is_honeypot, buy_tax, sell_tax, status
        
        return True, 0, 0, "⚠️ API indisponível"
        
    except Exception as e:
        logging.error(f"Erro Honeypot check: {e}")
        return True, 0, 0, "⚠️ Erro na verificação"

def filter_recent_tokens(pairs, chain):
    """Filtra tokens com janela temporal AMPLIADA para memecoins"""
    recent_tokens = []
    max_age_hours = CHAINS[chain].get("max_age_days", 7) * 24
    
    for pair in pairs:
        try:
            created_at = pair.get("pairCreatedAt")
            if not created_at:
                recent_tokens.append(pair)
                continue
                
            created_time = datetime.fromtimestamp(created_at / 1000)
            age = datetime.now() - created_time
            age_hours = age.total_seconds() / 3600
            
            if MIN_AGE_HOURS <= age_hours <= max_age_hours:
                recent_tokens.append(pair)
                
        except Exception as e:
            continue
    
    return recent_tokens

def analyze_token(pair, chain):
    """Analisa um token com foco em MEMECOINS"""
    base_token = pair.get("baseToken", {})
    
    token_address = base_token.get("address")
    token_name = base_token.get("name", "Unknown")[:20] or "Unknown"
    token_symbol = base_token.get("symbol", "UNKNOWN") or "UNKNOWN"
    
    liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
    volume_24h = pair.get("volume", {}).get("h24", 0) or 0
    volume_6h = pair.get("volume", {}).get("h6", 0) or 0
    price = pair.get("priceUsd", "0") or "0"
    price_change_24h = pair.get("priceChange", {}).get("h24", 0) or 0
    created_at = pair.get("pairCreatedAt", 0)
    dex_id = pair.get("dexId", "Unknown").lower()
    
    # 🔒 VERIFICAÇÕES DE SEGURANÇA
    security_checks = []
    security_score = 0
    
    # 1. Verificar Honeypot
    is_safe, buy_tax, sell_tax, honeypot_status = check_honeypot(CHAINS[chain]["chain_id"], token_address)
    security_checks.append(honeypot_status)
    
    if "HONEYPOT" in honeypot_status:
        security_score -= 10
    elif "✅" in honeypot_status:
        security_score += 2
    
    # 2. Verificar taxas
    if chain in ["ethereum", "bsc"]:
        if buy_tax > 15 or sell_tax > 15:
            security_checks.append(f"⚠️ Taxas altas (C: {buy_tax}%, V: {sell_tax}%)")
            security_score -= 1
        else:
            security_checks.append(f"✅ Taxas OK (C: {buy_tax}%, V: {sell_tax}%)")
            security_score += 1
    
    # 3. Verificar DEX confiável
    is_reliable_dex = any(dex in dex_id for dex in RELIABLE_DEXS.get(chain, []))
    if is_reliable_dex:
        security_checks.append(f"✅ {dex_id.capitalize()}")
        security_score += 2
    else:
        security_checks.append(f"⚠️ DEX: {dex_id}")
        security_score -= 1
    
    # 4. Verificar idade do contrato
    age_hours = 999
    age_days = 0
    if created_at:
        try:
            created_time = datetime.fromtimestamp(created_at / 1000)
            age = datetime.now() - created_time
            age_hours = age.total_seconds() / 3600
            age_days = age_hours / 24
        except:
            age_hours = 999
    
    # SCORE POR IDADE
    age_score = 0
    if age_hours < 24:
        age_score = 3
        age_str = f"🆕 {age_hours:.1f}h"
    elif age_hours < 72:
        age_score = 2
        age_str = f"🔥 {age_days:.1f}d"
    elif age_hours < 168:
        age_score = 1
        age_str = f"⏰ {age_days:.1f}d"
    else:
        age_str = f"📅 {age_days:.1f}d"
    
    security_checks.append(age_str)
    security_score += age_score
    
    # 📈 ANÁLISE DE MERCADO
    score = 0
    details = []
    
    # 1. VOLUME 
    volume_score = 0
    if volume_24h > 100000:
        volume_score = 3
        details.append(f"📈 Volume: ${volume_24h:,.0f}")
    elif volume_24h > 50000:
        volume_score = 2
        details.append(f"📊 Volume: ${volume_24h:,.0f}")
    elif volume_24h > 20000:
        volume_score = 1
        details.append(f"📉 Volume: ${volume_24h:,.0f}")
    else:
        details.append(f"💤 Volume: ${volume_24h:,.0f}")
    
    score += volume_score
    
    # 2. LIQUIDEZ
    liquidity_score = 0
    if liquidity > 50000:
        liquidity_score = 2
        details.append(f"💰 Liquidez: ${liquidity:,.0f}")
    elif liquidity > 20000:
        liquidity_score = 1
        details.append(f"💧 Liquidez: ${liquidity:,.0f}")
    else:
        details.append(f"💦 Liquidez: ${liquidity:,.0f}")
    
    score += liquidity_score
    
    # 3. PRICE CHANGE
    price_score = 0
    if price_change_24h > 50:
        price_score = 3
        details.append(f"🚀 +{price_change_24h:.1f}%")
    elif price_change_24h > 20:
        price_score = 2
        details.append(f"📈 +{price_change_24h:.1f}%")
    elif price_change_24h > 0:
        price_score = 1
        details.append(f"📊 +{price_change_24h:.1f}%")
    elif price_change_24h < -20:
        price_score = -1
        details.append(f"📉 {price_change_24h:.1f}%")
    else:
        details.append(f"➡️ {price_change_24h:.1f}%")
    
    score += price_score
    
    # 4. BÔNUS PARA MEMECOINS
    bonus_score = 0
    if volume_6h > volume_24h * 0.5:
        bonus_score += 1
        details.append("⚡ Volume recente")
    
    if any(x in token_name.lower() for x in ['dog', 'cat', 'ape', 'moon', 'coin', 'token']):
        bonus_score += 1
        details.append("🎯 Nome de meme")
    
    score += bonus_score
    
    # Adicionar score de segurança
    total_score = score + security_score
    
    return {
        "address": token_address,
        "name": token_name,
        "symbol": token_symbol,
        "price": price,
        "liquidity": liquidity,
        "volume_24h": volume_24h,
        "price_change_24h": price_change_24h,
        "age_hours": age_hours,
        "age_days": age_days,
        "score": total_score,
        "market_score": score,
        "security_score": security_score,
        "details": details,
        "security_checks": security_checks,
        "is_safe": is_safe and security_score >= 1,
        "url": pair.get("url", ""),
        "dex": dex_id,
        "explorer": f"{CHAINS[chain]['explorer']}{token_address}",
        "chain": chain
    }

def create_message(analysis, chain):
    """Cria mensagem focada em memecoins"""
    chain_display = chain.upper()
    native_token = CHAINS[chain]["native_token"]
    
    if not analysis["is_safe"]:
        emoji = "🚨"
        message = f"{emoji} <b>ALERTA - {chain_display}</b>\n\n"
    else:
        emoji = "🚀" if analysis["score"] >= 8 else "⭐" if analysis["score"] >= 5 else "🔍"
        message = f"{emoji} <b>MEMECOIN {chain_display}</b>\n\n"
    
    message += f"<b>{analysis['name']} ({analysis['symbol']})</b>\n"
    message += f"💵 <b>Preço:</b> ${analysis['price']}\n"
    message += f"📊 <b>Variação 24h:</b> {analysis['price_change_24h']:.1f}%\n"
    message += f"⭐ <b>Score Total:</b> {analysis['score']}/10\n"
    message += f"📈 <b>Score Mercado:</b> {analysis['market_score']}/8\n"
    message += f"🛡️ <b>Segurança:</b> {analysis['security_score']}/5\n"
    message += f"🎯 <b>Idade:</b> {analysis['age_days']:.1f} dias\n\n"
    
    message += "<b>📊 Análise:</b>\n"
    for detail in analysis["details"]:
        message += f"• {detail}\n"
    
    message += f"\n<b>🔒 Verificações:</b>\n"
    for check in analysis["security_checks"]:
        message += f"• {check}\n"
    
    message += f"\n<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis['url']}'>DexScreener</a>\n"
    message += f"• <a href='{analysis['explorer']}'>Explorer</a>\n"
    message += f"• <b>DEX:</b> {analysis['dex']}\n"
    message += f"• <b>Rede:</b> {chain_display}"
    
    if analysis["score"] >= 8:
        message += f"\n\n🎯 <b>POTENCIAL ALTO!</b>"
    elif not analysis["is_safe"]:
        message += f"\n\n🚨 <b>VERIFIQUE COM CUIDADO!</b>"
    
    return message

def monitor_tokens():
    """Monitora tokens com foco em memecoins"""
    logging.info("🔍 Procurando memecoins em todas as chains...")
    tokens_encontrados = 0
    
    for chain in CHAINS:
        if not CHAINS[chain]["enabled"]:
            continue
            
        try:
            all_pairs = get_token_pairs(chain)
            
            if not all_pairs:
                continue
            
            recent_pairs = filter_recent_tokens(all_pairs, chain)
            logging.info(f"📊 {chain}: {len(recent_pairs)} tokens (até {CHAINS[chain]['max_age_days']} dias)")
            
            for pair in recent_pairs:
                token_address = pair.get("baseToken", {}).get("address")
                
                if token_address and token_address not in vistos:
                    vistos.add(token_address)
                    
                    analysis = analyze_token(pair, chain)
                    
                    if analysis["score"] >= 4:
                        message = create_message(analysis, chain)
                        if send_telegram(message):
                            tokens_encontrados += 1
                            status = "SEGURO" if analysis["is_safe"] else "ALERTA"
                            logging.info(f"✅ {chain}: {analysis['symbol']} (Score: {analysis['score']}, {status})")
                        time.sleep(1)
                    
        except Exception as e:
            logging.error(f"Erro em {chain}: {e}")
    
    return tokens_encontrados

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    logging.info(f"🤖 Bot Memecoin Hunter iniciado! Janela: {MAX_AGE_DAYS} dias")
    
    if send_telegram(f"🤖 <b>Memecoin Hunter iniciado!</b>\n🔍 Janela: {MAX_AGE_DAYS} dias\n🎯 Foco: ETH, BSC, SOL\n🛡️ Verificações de segurança ativas"):
        logging.info("✅ Conexão com Telegram OK!")
    
    while True:
        try:
            tokens_encontrados = monitor_tokens()
            logging.info(f"🎉 {tokens_encontrados} memecoins analisados!")
            
            wait_time = random.randint(300, 480)
            logging.info(f"⏳ Próxima verificação em {wait_time//60} minutos...")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
