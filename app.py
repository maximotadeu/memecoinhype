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

# APIs de segurança
HONEYPOT_CHECK_API = "https://api.honeypot.is/v2/IsHoneypot"

# Chains suportadas (Ethereum, BSC, Solana)
CHAINS = {
    "ethereum": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0x2170ed0880ac9a755fd29b2688956bd959f933f8",  # ETH
        "explorer": "https://etherscan.io/token/",
        "chain_id": "eth",
        "native_token": "ETH",
        "enabled": True
    },
    "bsc": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # BNB
        "explorer": "https://bscscan.com/token/", 
        "chain_id": "bsc",
        "native_token": "BNB",
        "enabled": True
    },
    "solana": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112",  # SOL
        "explorer": "https://solscan.io/token/",
        "chain_id": "sol",
        "native_token": "SOL",
        "enabled": True
    }
}

# DEXs confiáveis por chain
RELIABLE_DEXS = {
    "ethereum": ["uniswap", "sushiswap", "pancakeswap", "shibaswap"],
    "bsc": ["pancakeswap", "biswap", "apeswap", "babyswap"],
    "solana": ["raydium", "orca", "jupiter", "meteora"]
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

def check_honeypot(chain, token_address):
    """Verifica se é honeypot (apenas para EVM chains)"""
    if chain not in ["eth", "bsc"]:  # Solana não suporta honeypot.is
        return True, 0, 0, "🔓 Rede não suporta verificação"
    
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

def check_liquidity_lock(pair, chain):
    """Verifica indicadores de liquidez travada"""
    try:
        dex_id = pair.get("dexId", "").lower()
        
        # Verificar se é DEX confiável para a chain
        is_reliable_dex = any(dex in dex_id for dex in RELIABLE_DEXS.get(chain, []))
        
        # Verificar liquidez - mínimo por chain
        liquidity = pair.get("liquidity", {}).get("usd", 0)
        
        # Mínimos diferentes por chain
        min_liquidity = {
            "ethereum": 5000,
            "bsc": 3000, 
            "solana": 2000  # Solana pode ter liquidez menor
        }
        
        has_min_liquidity = liquidity > min_liquidity.get(chain, 2000)
        
        # Verificar volume mínimo
        volume_24h = pair.get("volume", {}).get("h24", 0)
        has_min_volume = volume_24h > 1000
        
        return is_reliable_dex and has_min_liquidity and has_min_volume
        
    except Exception as e:
        logging.error(f"Erro liquidity check: {e}")
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
            return pairs[:20]  # Pegar os 20 com mais volume
            
        return []
    except Exception as e:
        logging.error(f"❌ Erro em {chain}: {e}")
        return []

def analyze_token(pair, chain):
    """Analisa um token com verificações de segurança"""
    base_token = pair.get("baseToken", {})
    
    token_address = base_token.get("address")
    token_name = base_token.get("name", "Unknown")[:25] or "Unknown"
    token_symbol = base_token.get("symbol", "UNKNOWN") or "UNKNOWN"
    
    liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
    volume_24h = pair.get("volume", {}).get("h24", 0) or 0
    price = pair.get("priceUsd", "0") or "0"
    created_at = pair.get("pairCreatedAt", 0)
    dex_id = pair.get("dexId", "Unknown")
    
    # 🔒 VERIFICAÇÕES DE SEGURANÇA
    security_checks = []
    security_score = 0
    
    # 1. Verificar Honeypot (apenas EVM)
    is_safe, buy_tax, sell_tax, honeypot_status = check_honeypot(CHAINS[chain]["chain_id"], token_address)
    security_checks.append(honeypot_status)
    
    if "HONEYPOT" in honeypot_status:
        security_score -= 10
    elif "✅" in honeypot_status:
        security_score += 2
    
    # 2. Verificar taxas (apenas EVM)
    if chain in ["ethereum", "bsc"]:
        if buy_tax > 20 or sell_tax > 20:
            security_checks.append(f"⚠️ Taxas altas (Compra: {buy_tax}%, Venda: {sell_tax}%)")
            security_score -= 2
        else:
            security_checks.append(f"✅ Taxas OK (Compra: {buy_tax}%, Venda: {sell_tax}%)")
            security_score += 1
    
    # 3. Verificar liquidez e DEX confiável
    has_liquidity_lock = check_liquidity_lock(pair, chain)
    if has_liquidity_lock:
        security_checks.append("✅ Liquidez/DEX OK")
        security_score += 2
    else:
        security_checks.append("⚠️ Liquidez baixa/DEX não confiável")
        security_score -= 1
    
    # 4. Verificar idade do contrato
    age_hours = 999
    if created_at:
        try:
            created_time = datetime.fromtimestamp(created_at / 1000)
            age = datetime.now() - created_time
            age_hours = age.total_seconds() / 3600
        except:
            age_hours = 999
    
    if age_hours < 24:
        security_checks.append(f"🆕 {age_hours:.1f}h")
        security_score += 1
    else:
        security_checks.append(f"📅 {age_hours:.1f}h")
    
    # Score baseado em vários fatores
    score = 0
    details = []
    
    # Liquidez (com pesos diferentes por chain)
    liquidity_thresholds = {
        "ethereum": [50000, 20000, 5000],
        "bsc": [30000, 10000, 3000],
        "solana": [20000, 5000, 1000]
    }
    
    thresholds = liquidity_thresholds.get(chain, [20000, 5000, 1000])
    
    if liquidity > thresholds[0]:
        score += 3
        details.append(f"💰 ${liquidity:,.0f}")
    elif liquidity > thresholds[1]:
        score += 2
        details.append(f"💧 ${liquidity:,.0f}")
    elif liquidity > thresholds[2]:
        score += 1
        details.append(f"💦 ${liquidity:,.0f}")
    else:
        details.append(f"🌵 ${liquidity:,.0f}")
    
    # Volume
    if volume_24h > 50000:
        score += 2
        details.append(f"📈 ${volume_24h:,.0f}")
    elif volume_24h > 20000:
        score += 1
        details.append(f"📊 ${volume_24h:,.0f}")
    else:
        details.append(f"📉 ${volume_24h:,.0f}")
    
    # Adicionar score de segurança
    score += security_score
    
    # Para Solana, ajustar critérios
    if chain == "solana":
        # Raydium é muito confiável
        if "raydium" in dex_id.lower():
            security_score += 1
            score += 1
            security_checks.append("✅ Raydium (Confiável)")
    
    return {
        "address": token_address,
        "name": token_name,
        "symbol": token_symbol,
        "price": price,
        "liquidity": liquidity,
        "volume": volume_24h,
        "age_hours": age_hours,
        "score": score,
        "security_score": security_score,
        "details": details,
        "security_checks": security_checks,
        "buy_tax": buy_tax,
        "sell_tax": sell_tax,
        "is_safe": is_safe and security_score >= 0,
        "url": pair.get("url", ""),
        "dex": dex_id,
        "explorer": f"{CHAINS[chain]['explorer']}{token_address}",
        "chain": chain
    }

def create_message(analysis, chain):
    """Cria mensagem para Telegram com alertas de segurança"""
    chain_display = chain.upper()
    native_token = CHAINS[chain]["native_token"]
    
    if not analysis["is_safe"]:
        emoji = "🚨"
        message = f"{emoji} <b>ALERTA - {chain_display}</b>\n\n"
    else:
        emoji = "🚀" if analysis["score"] >= 6 else "⭐" if analysis["score"] >= 4 else "🔍"
        message = f"{emoji} <b>TOKEN {chain_display}</b>\n\n"
    
    message += f"<b>{analysis['name']} ({analysis['symbol']})</b>\n"
    message += f"💵 <b>Preço:</b> ${analysis['price']}\n"
    message += f"⭐ <b>Score:</b> {analysis['score']}/10\n"
    message += f"🛡️ <b>Segurança:</b> {analysis['security_score']}/5\n"
    message += f"🏦 <b>Rede:</b> {chain_display} ({native_token})\n\n"
    
    message += "<b>📊 Estatísticas:</b>\n"
    for detail in analysis["details"]:
        message += f"• {detail}\n"
    
    message += f"\n<b>🔒 Verificações:</b>\n"
    for check in analysis["security_checks"]:
        message += f"• {check}\n"
    
    message += f"\n<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis['url']}'>DexScreener</a>\n"
    message += f"• <a href='{analysis['explorer']}'>Explorer</a>\n"
    message += f"• <b>DEX:</b> {analysis['dex']}"
    
    if not analysis["is_safe"]:
        message += f"\n\n🚨 <b>ATENÇÃO:</b> Verifique cuidadosamente!"
    
    return message

def monitor_tokens():
    """Monitora tokens com verificações de segurança"""
    logging.info("🔍 Procurando tokens em todas as chains...")
    tokens_encontrados = 0
    
    for chain in CHAINS:
        if not CHAINS[chain]["enabled"]:
            continue
            
        try:
            all_pairs = get_token_pairs(chain)
            
            if not all_pairs:
                continue
            
            logging.info(f"📊 {chain}: {len(all_pairs)} pares para análise")
            
            for pair in all_pairs:
                token_address = pair.get("baseToken", {}).get("address")
                
                if token_address and token_address not in vistos:
                    vistos.add(token_address)
                    
                    analysis = analyze_token(pair, chain)
                    
                    # Notificar todos os tokens, mas com alertas claros
                    message = create_message(analysis, chain)
                    if send_telegram(message):
                        tokens_encontrados += 1
                        status = "SEGURO" if analysis["is_safe"] else "ALERTA"
                        logging.info(f"✅ {chain}: {analysis['symbol']} ({status})")
                    time.sleep(1)
                    
        except Exception as e:
            logging.error(f"Erro em {chain}: {e}")
    
    return tokens_encontrados

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    logging.info("🤖 Bot iniciado! Monitorando Ethereum, BSC e Solana...")
    
    if send_telegram("🤖 <b>Bot Multi-Chain iniciado!</b>\n🔍 Monitorando: ETH, BSC, SOL\n🛡️ Verificações de segurança ativas"):
        logging.info("✅ Conexão com Telegram OK!")
    
    while True:
        try:
            tokens_encontrados = monitor_tokens()
            logging.info(f"🎉 {tokens_encontrados} tokens analisados!")
            
            wait_time = random.randint(300, 480)
            logging.info(f"⏳ Próxima verificação em {wait_time//60} minutos...")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
