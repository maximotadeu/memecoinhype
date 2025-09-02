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

# JANELA TEMPORAL BEM AMPLIADA
MAX_AGE_DAYS = 14  # Até 14 dias! 
MIN_AGE_HOURS = 1   # Apenas 1 hora mínimo

# APIs de segurança
HONEYPOT_CHECK_API = "https://api.honeypot.is/v2/IsHoneypot"

# Chains suportadas - MAIS URLs para pegar mais tokens
CHAINS = {
    "ethereum": {
        "urls": [
            "https://api.dexscreener.com/latest/dex/tokens/0x2170ed0880ac9a755fd29b2688956bd959f933f8",  # ETH
            "https://api.dexscreener.com/latest/dex/tokens/0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
            "https://api.dexscreener.com/latest/dex/tokens/0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"   # WBTC
        ],
        "explorer": "https://etherscan.io/token/",
        "chain_id": "eth",
        "native_token": "ETH",
        "enabled": True,
        "max_age_days": 10
    },
    "bsc": {
        "urls": [
            "https://api.dexscreener.com/latest/dex/tokens/0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # BNB
            "https://api.dexscreener.com/latest/dex/tokens/0x55d398326f99059ff775485246999027b3197955",  # BUSD
            "https://api.dexscreener.com/latest/dex/tokens/0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"   # USDC
        ],
        "explorer": "https://bscscan.com/token/", 
        "chain_id": "bsc",
        "native_token": "BNB",
        "enabled": True,
        "max_age_days": 14  # BSC tem mais memecoins
    },
    "solana": {
        "urls": [
            "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112",  # SOL
            "https://api.dexscreener.com/latest/dex/tokens/EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "https://api.dexscreener.com/latest/dex/tokens/Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"   # USDT
        ],
        "explorer": "https://solscan.io/token/",
        "chain_id": "sol",
        "native_token": "SOL",
        "enabled": True,
        "max_age_days": 7
    }
}

# DEXs confiáveis - MAIS opções
RELIABLE_DEXS = {
    "ethereum": ["uniswap", "sushiswap", "shibaswap", "pancakeswap"],
    "bsc": ["pancakeswap", "biswap", "apeswap", "babyswap", "julswap"],
    "solana": ["raydium", "orca", "jupiter", "meteora", "aldrin"]
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
    """Busca pares de MÚLTIPLOS tokens para pegar mais dados"""
    all_pairs = []
    
    for url in CHAINS[chain]["urls"]:
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                pairs = data.get("pairs", [])
                
                # Ordenar por volume (mais populares primeiro)
                pairs.sort(key=lambda x: x.get("volume", {}).get("h24", 0), reverse=True)
                all_pairs.extend(pairs[:15])  # Pegar os 15 de cada token
                
                logging.info(f"✅ {chain}: {len(pairs)} pares de {url.split('/')[-1]}")
                
        except Exception as e:
            logging.error(f"❌ Erro em {chain} - {url}: {e}")
    
    # Remover duplicatas
    unique_pairs = {}
    for pair in all_pairs:
        pair_address = pair.get("pairAddress")
        if pair_address:
            unique_pairs[pair_address] = pair
    
    logging.info(f"📊 {chain}: {len(unique_pairs)} pares únicos encontrados")
    return list(unique_pairs.values())

def check_honeypot(chain, token_address):
    """Verifica se é honeypot - MAIS PERMISSIVO"""
    if chain not in ["eth", "bsc"]:
        return True, 0, 0, "🔓 Rede não suportada"
    
    try:
        url = f"{HONEYPOT_CHECK_API}?chain={chain}&token={token_address}"
        response = requests.get(url, timeout=10)  # Timeout menor
        
        if response.status_code == 200:
            data = response.json()
            simulation = data.get("simulation", {})
            
            is_honeypot = simulation.get("isHoneypot", False)
            buy_tax = simulation.get("buyTax", 0)
            sell_tax = simulation.get("sellTax", 0)
            
            # MAIS PERMISSIVO: Só alerta se for honeypot confirmado
            if is_honeypot:
                return False, buy_tax, sell_tax, "🚫 HONEYPOT"
            else:
                return True, buy_tax, sell_tax, "✅ Provavelmente seguro"
        
        return True, 0, 0, "⚠️ API indisponível"
        
    except Exception as e:
        # Em caso de erro, assume seguro
        return True, 0, 0, "⚠️ Erro na verificação"

def filter_recent_tokens(pairs, chain):
    """Filtra tokens com janela temporal BEM AMPLIADA"""
    recent_tokens = []
    max_age_hours = CHAINS[chain].get("max_age_days", 14) * 24
    
    for pair in pairs:
        try:
            created_at = pair.get("pairCreatedAt")
            if not created_at:
                # Inclui TODOS os tokens sem data
                recent_tokens.append(pair)
                continue
                
            created_time = datetime.fromtimestamp(created_at / 1000)
            age = datetime.now() - created_time
            age_hours = age.total_seconds() / 3600
            
            # JANELA MUITO AMPLIADA: 1 hora até 14 dias
            if MIN_AGE_HOURS <= age_hours <= max_age_hours:
                recent_tokens.append(pair)
                
        except Exception as e:
            # Inclui mesmo com erro
            recent_tokens.append(pair)
    
    return recent_tokens

def analyze_token(pair, chain):
    """Analisa um token com regras MUITO RELAXADAS"""
    base_token = pair.get("baseToken", {})
    
    token_address = base_token.get("address")
    token_name = base_token.get("name", "Unknown")[:25] or "Unknown"
    token_symbol = base_token.get("symbol", "UNKNOWN") or "UNKNOWN"
    
    liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
    volume_24h = pair.get("volume", {}).get("h24", 0) or 0
    price = pair.get("priceUsd", "0") or "0"
    price_change_24h = pair.get("priceChange", {}).get("h24", 0) or 0
    created_at = pair.get("pairCreatedAt", 0)
    dex_id = pair.get("dexId", "Unknown").lower()
    
    # 🔒 VERIFICAÇÕES DE SEGURANÇA (MUITO RELAXADAS)
    security_checks = []
    security_score = 2  # Score base positivo
    
    # 1. Verificar Honeypot (mais permissivo)
    is_safe, buy_tax, sell_tax, honeypot_status = check_honeypot(CHAINS[chain]["chain_id"], token_address)
    security_checks.append(honeypot_status)
    
    if "HONEYPOT" in honeypot_status:
        security_score = -10  # Só penaliza se for honeypot confirmado
    else:
        security_score += 1
    
    # 2. Verificar taxas (bem relaxado)
    if chain in ["ethereum", "bsc"]:
        if buy_tax > 25 or sell_tax > 25:  # Limite bem alto
            security_checks.append(f"⚠️ Taxas altas (C: {buy_tax}%, V: {sell_tax}%)")
            security_score -= 1
        else:
            security_checks.append(f"✅ Taxas OK (C: {buy_tax}%, V: {sell_tax}%)")
            security_score += 1
    
    # 3. Verificar DEX (aceita quase todos)
    is_reliable_dex = any(dex in dex_id for dex in RELIABLE_DEXS.get(chain, []))
    if is_reliable_dex:
        security_checks.append(f"✅ {dex_id.capitalize()}")
        security_score += 1
    else:
        security_checks.append(f"ℹ️ DEX: {dex_id}")
        # Não penaliza DEX não confiável
    
    # 4. Verificar idade (muito relaxado)
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
    
    age_str = f"📅 {age_days:.1f}d" if age_days >= 1 else f"🆕 {age_hours:.1f}h"
    security_checks.append(age_str)
    
    # 📈 ANÁLISE DE MERCADO (MUITO RELAXADA)
    score = 0
    details = []
    
    # 1. VOLUME (critério bem baixo)
    if volume_24h > 10000:
        score += 2
        details.append(f"📈 Volume: ${volume_24h:,.0f}")
    elif volume_24h > 5000:
        score += 1
        details.append(f"📊 Volume: ${volume_24h:,.0f}")
    elif volume_24h > 1000:
        score += 0.5
        details.append(f"📉 Volume: ${volume_24h:,.0f}")
    else:
        details.append(f"💤 Volume: ${volume_24h:,.0f}")
    
    # 2. LIQUIDEZ (critério bem baixo)
    if liquidity > 10000:
        score += 2
        details.append(f"💰 Liquidez: ${liquidity:,.0f}")
    elif liquidity > 5000:
        score += 1
        details.append(f"💧 Liquidez: ${liquidity:,.0f}")
    elif liquidity > 1000:
        score += 0.5
        details.append(f"💦 Liquidez: ${liquidity:,.0f}")
    else:
        details.append(f"🌵 Liquidez: ${liquidity:,.0f}")
    
    # 3. PRICE CHANGE (qualquer positivo ganha pontos)
    if price_change_24h > 10:
        score += 2
        details.append(f"🚀 +{price_change_24h:.1f}%")
    elif price_change_24h > 0:
        score += 1
        details.append(f"📈 +{price_change_24h:.1f}%")
    elif price_change_24h > -10:
        score += 0.5
        details.append(f"➡️ {price_change_24h:.1f}%")
    else:
        details.append(f"📉 {price_change_24h:.1f}%")
    
    # 4. BÔNUS (qualquer coisa ganha pontos)
    score += 1  # Bônus base para todos
    
    if any(x in token_name.lower() for x in ['dog', 'cat', 'ape', 'moon', 'coin', 'token', 'kitty', 'baby']):
        score += 1
        details.append("🎯 Nome de meme")
    
    if any(x in dex_id for x in ['raydium', 'pancake', 'uniswap']):
        score += 1
        details.append("🏆 DEX popular")
    
    # Score total MUITO relaxado
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
        "security_score": security_score,
        "details": details,
        "security_checks": security_checks,
        "is_safe": security_score > -5,  # Muito permissivo
        "url": pair.get("url", ""),
        "dex": dex_id,
        "explorer": f"{CHAINS[chain]['explorer']}{token_address}",
        "chain": chain
    }

def create_message(analysis, chain):
    """Cria mensagem MUITO simples"""
    chain_display = chain.upper()
    
    emoji = "🚀" if analysis["score"] > 5 else "⭐" if analysis["score"] > 3 else "🔍"
    message = f"{emoji} <b>{chain_display} MEME</b>\n\n"
    
    message += f"<b>{analysis['name']} ({analysis['symbol']})</b>\n"
    message += f"💵 <b>Preço:</b> ${analysis['price']}\n"
    message += f"📊 <b>Volume:</b> ${analysis['volume_24h']:,.0f}\n"
    message += f"📈 <b>Variação:</b> {analysis['price_change_24h']:.1f}%\n"
    message += f"⭐ <b>Score:</b> {analysis['score']:.1f}/10\n\n"
    
    message += "<b>📊 Info:</b>\n"
    for detail in analysis["details"][:3]:  # Apenas 3 detalhes
        message += f"• {detail}\n"
    
    message += f"\n<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis['url']}'>DexScreener</a>\n"
    message += f"• <a href='{analysis['explorer']}'>Explorer</a>\n"
    message += f"• <b>DEX:</b> {analysis['dex']}"
    
    if analysis["score"] > 6:
        message += f"\n\n🎯 <b>POTENCIAL!</b>"
    
    return message

def monitor_tokens():
    """Monitora tokens com regras MUITO RELAXADAS"""
    logging.info("🔍 Procurando memecoins (regras relaxadas)...")
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
                    
                    # NOTIFICA QUASE TUDO - Score muito baixo
                    if analysis["score"] >= 1:  # Quase qualquer token
                        message = create_message(analysis, chain)
                        if send_telegram(message):
                            tokens_encontrados += 1
                            logging.info(f"✅ {chain}: {analysis['symbol']} (Score: {analysis['score']:.1f})")
                        time.sleep(0.5)  # Delay bem curto
                    
        except Exception as e:
            logging.error(f"Erro em {chain}: {e}")
    
    return tokens_encontrados

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    logging.info(f"🤖 Bot Memecoin Hunter (RELAXADO) iniciado!")
    
    if send_telegram(f"🤖 <b>Memecoin Hunter RELAXADO iniciado!</b>\n🔍 Janela: até 14 dias\n🎯 Notificando quase todos os tokens\n🛡️ Verificações leves"):
        logging.info("✅ Conexão com Telegram OK!")
    
    while True:
        try:
            tokens_encontrados = monitor_tokens()
            logging.info(f"🎉 {tokens_encontrados} tokens notificados!")
            
            wait_time = random.randint(180, 300)  # 3-5 minutos
            logging.info(f"⏳ Próxima verificação em {wait_time//60} minutos...")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
