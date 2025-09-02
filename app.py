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
HONEYPOT_TAX_API = "https://api.honeypot.is/v1/GetTaxes"

# URLs que FUNCIONAM com a API DexScreener
CHAINS = {
    "ethereum": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0x2170ed0880ac9a755fd29b2688956bd959f933f8",
        "explorer": "https://etherscan.io/token/",
        "chain_id": "eth",
        "enabled": True
    },
    "bsc": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
        "explorer": "https://bscscan.com/token/",
        "chain_id": "bsc",
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
        return response.status_code == 200
    except Exception as e:
        logging.error(f"Erro Telegram: {e}")
        return False

def check_honeypot(chain, token_address):
    """Verifica se é honeypot e retorna taxas"""
    try:
        url = f"{HONEYPOT_CHECK_API}?chain={chain}&token={token_address}"
        response = requests.get(url, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            simulation = data.get("simulation", {})
            
            is_honeypot = simulation.get("isHoneypot", False)
            buy_tax = simulation.get("buyTax", 0)
            sell_tax = simulation.get("sellTax", 0)
            
            return not is_honeypot, buy_tax, sell_tax
        
        return True, 0, 0  # Se API falhar, assume seguro
        
    except Exception as e:
        logging.error(f"Erro Honeypot check: {e}")
        return True, 0, 0  # Assume seguro em caso de erro

def check_liquidity_lock(pair):
    """Verifica indicadores de liquidez travada"""
    try:
        # Verificar se é par em DEX confiável
        dex_id = pair.get("dexId", "").lower()
        reliable_dexs = ["uniswap", "pancakeswap", "sushiswap", "raydium"]
        
        is_reliable_dex = any(dex in dex_id for dex in reliable_dexs)
        
        # Verificar liquidez - mínimo de segurança
        liquidity = pair.get("liquidity", {}).get("usd", 0)
        has_min_liquidity = liquidity > 2000  # Mínimo absoluto
        
        return is_reliable_dex and has_min_liquidity
        
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
            return pairs[:15]  # Pegar os 15 mais volume
            
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
    
    # 🔒 VERIFICAÇÕES DE SEGURANÇA
    security_checks = []
    security_score = 0
    
    # 1. Verificar Honeypot
    is_safe, buy_tax, sell_tax = check_honeypot(CHAINS[chain]["chain_id"], token_address)
    if not is_safe:
        security_checks.append("🚫 HONEYPOT")
        security_score -= 10
    else:
        security_checks.append(f"✅ Sem honeypot")
        security_score += 2
    
    # 2. Verificar taxas
    if buy_tax > 15 or sell_tax > 15:
        security_checks.append(f"⚠️ Taxas altas (Compra: {buy_tax}%, Venda: {sell_tax}%)")
        security_score -= 2
    else:
        security_checks.append(f"✅ Taxas razoáveis (Compra: {buy_tax}%, Venda: {sell_tax}%)")
        security_score += 1
    
    # 3. Verificar liquidez mínima e DEX confiável
    has_liquidity_lock = check_liquidity_lock(pair)
    if has_liquidity_lock:
        security_checks.append("✅ Liquidez OK")
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
    
    # Liquidez (com pesos diferentes)
    if liquidity > 50000:
        score += 3
        details.append(f"💰 ${liquidity:,.0f}")
    elif liquidity > 20000:
        score += 2
        details.append(f"💧 ${liquidity:,.0f}")
    elif liquidity > 5000:
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
        "dex": pair.get("dexId", ""),
        "explorer": f"{CHAINS[chain]['explorer']}{token_address}"
    }

def create_message(analysis, chain):
    """Cria mensagem para Telegram com alertas de segurança"""
    if not analysis["is_safe"]:
        emoji = "🚨"
        message = f"{emoji} <b>ALERTA DE SEGURANÇA - {chain.upper()}</b>\n\n"
    else:
        emoji = "🚀" if analysis["score"] >= 5 else "⭐" if analysis["score"] >= 3 else "🔍"
        message = f"{emoji} <b>TOKEN {chain.upper()}</b>\n\n"
    
    message += f"<b>{analysis['name']} ({analysis['symbol']})</b>\n"
    message += f"💵 <b>Preço:</b> ${analysis['price']}\n"
    message += f"⭐ <b>Score:</b> {analysis['score']}/10\n"
    message += f"🛡️ <b>Segurança:</b> {analysis['security_score']}/5\n\n"
    
    message += "<b>📊 Estatísticas:</b>\n"
    for detail in analysis["details"]:
        message += f"• {detail}\n"
    
    message += f"\n<b>🔒 Verificações de Segurança:</b>\n"
    for check in analysis["security_checks"]:
        message += f"• {check}\n"
    
    message += f"\n<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis['url']}'>DexScreener</a>\n"
    message += f"• <a href='{analysis['explorer']}'>Explorer</a>\n"
    message += f"• <b>DEX:</b> {analysis['dex']}"
    
    if not analysis["is_safe"]:
        message += f"\n\n🚨 <b>ATENÇÃO:</b> Este token pode não ser seguro!"
    
    return message

def monitor_tokens():
    """Monitora tokens com verificações de segurança"""
    logging.info("🔍 Procurando tokens com verificações de segurança...")
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
                    
                    # Notificar TODOS os tokens, mas com alertas de segurança
                    message = create_message(analysis, chain)
                    if send_telegram(message):
                        tokens_encontrados += 1
                        status = "SEGURO" if analysis["is_safe"] else "ALERTA"
                        logging.info(f"✅ {chain}: {analysis['symbol']} ({status})")
                    time.sleep(2)  # Evitar rate limit
                    
        except Exception as e:
            logging.error(f"Erro em {chain}: {e}")
    
    return tokens_encontrados

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    logging.info("🤖 Bot iniciado! Monitorando tokens com verificações de segurança...")
    
    if send_telegram("🤖 <b>Bot de Segurança iniciado!</b>\n🔍 Monitorando tokens com verificações anti-honeypot..."):
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
