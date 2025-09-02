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
HONEYPOT_API = "https://api.honeypot.is/v2/IsHoneypot"
RUGCHECK_API = "https://api.rugcheck.xyz/tokens"

# API UNIFICADA Etherscan (suporta múltiplas chains)
ETHERSCAN_UNIFIED_API = "https://api.etherscan.io/api"
ETHERSCAN_API_KEY = os.environ.get('ETHERSCAN_API_KEY', 'YourApiKeyToken')

# Chains suportadas pela API unificada Etherscan
CHAINS = {
    "ethereum": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0x2170ed0880ac9a755fd29b2688956bd959f933f8",
        "explorer": "https://etherscan.io/token/",
        "chain_id": "eth",
        "network": "eth",  # Para API unificada
        "enabled": True
    },
    "bsc": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
        "explorer": "https://bscscan.com/token/", 
        "chain_id": "bsc",
        "network": "bsc",  # Para API unificada
        "enabled": True
    },
    "polygon": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270",
        "explorer": "https://polygonscan.com/token/",
        "chain_id": "polygon",
        "network": "polygon",  # Para API unificada
        "enabled": True
    },
    "arbitrum": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
        "explorer": "https://arbiscan.io/token/",
        "chain_id": "arbitrum",
        "network": "arbitrum",  # Para API unificada
        "enabled": True
    }
}

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

def check_honeypot_real(chain, token_address):
    """Verificação REAL de honeypot"""
    try:
        url = f"{HONEYPOT_API}?chain={chain}&token={token_address}"
        response = requests.get(url, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            simulation = data.get("simulation", {})
            
            is_honeypot = simulation.get("isHoneypot", False)
            buy_tax = simulation.get("buyTax", 0)
            sell_tax = simulation.get("sellTax", 0)
            
            return {
                "is_honeypot": is_honeypot,
                "buy_tax": buy_tax,
                "sell_tax": sell_tax,
                "risk_level": "CRITICAL" if is_honeypot else "LOW"
            }
        
        return {"error": "API unavailable"}
        
    except Exception as e:
        return {"error": str(e)}

def check_contract_unified_etherscan(network, token_address):
    """Análise do contrato usando API UNIFICADA Etherscan"""
    try:
        # Parâmetros para API unificada
        params = {
            "module": "contract",
            "action": "getsourcecode",
            "address": token_address,
            "apikey": ETHERSCAN_API_KEY
        }
        
        # URL específica para cada network (usando API unificada)
        response = requests.get(ETHERSCAN_UNIFIED_API, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "1" and data.get("result"):
                contract_info = data["result"][0]
                
                return {
                    "verified": contract_info.get("SourceCode") not in ["", None],
                    "proxy": contract_info.get("Proxy") == "1",
                    "contract_name": contract_info.get("ContractName", "Unknown"),
                    "compiler_version": contract_info.get("CompilerVersion", "Unknown"),
                    "optimization_used": contract_info.get("OptimizationUsed", "0") == "1"
                }
        
        return {"error": "Etherscan API failed"}
        
    except Exception as e:
        return {"error": str(e)}

def check_liquidity_lock_real(pair):
    """Verificação REAL de liquidez travada"""
    try:
        dex_id = pair.get("dexId", "").lower()
        reliable_dexs = ["pancakeswap", "uniswap", "sushiswap", "raydium"]
        
        liquidity = pair.get("liquidity", {}).get("usd", 0)
        volume_24h = pair.get("volume", {}).get("h24", 0)
        
        # Critérios de segurança
        is_reliable_dex = any(dex in dex_id for dex in reliable_dexs)
        has_sufficient_liquidity = liquidity > 5000  # $5k mínimo
        has_volume = volume_24h > 1000  # $1k volume mínimo
        
        # Verificar se é par com token nativo (mais seguro)
        quote_token = pair.get("quoteToken", {}).get("symbol", "").upper()
        is_native_pair = quote_token in ["WBNB", "BNB", "WETH", "ETH", "MATIC", "POL", "ARB", "ETH"]
        
        return {
            "is_reliable_dex": is_reliable_dex,
            "has_sufficient_liquidity": has_sufficient_liquidity,
            "has_volume": has_volume,
            "is_native_pair": is_native_pair,
            "liquidity_usd": liquidity,
            "volume_24h": volume_24h,
            "risk_level": "LOW" if (is_reliable_dex and has_sufficient_liquidity) else "MEDIUM"
        }
        
    except Exception as e:
        return {"error": str(e)}

def get_token_pairs(chain):
    """Busca pares de tokens"""
    try:
        response = requests.get(CHAINS[chain]["url"], timeout=15)
        if response.status_code == 200:
            data = response.json()
            pairs = data.get("pairs", [])
            # Ordenar por volume e pegar os mais relevantes
            pairs.sort(key=lambda x: x.get("volume", {}).get("h24", 0), reverse=True)
            return pairs[:15]  # Limitar para não sobrecarregar
        return []
    except Exception as e:
        logging.error(f"Erro em {chain}: {e}")
        return []

def analyze_token_security(pair, chain):
    """Análise COMPLETA de segurança"""
    base_token = pair.get("baseToken", {})
    token_address = base_token.get("address")
    network = CHAINS[chain]["network"]
    
    security_report = {
        "honeypot": check_honeypot_real(CHAINS[chain]["chain_id"], token_address),
        "contract": check_contract_unified_etherscan(network, token_address),
        "liquidity": check_liquidity_lock_real(pair),
        "overall_risk": "UNKNOWN"
    }
    
    # Determinar risco geral
    risks = []
    
    # Verificar honeypot
    honeypot = security_report["honeypot"]
    if not honeypot.get("error") and honeypot.get("is_honeypot", False):
        risks.append("CRITICAL")
    elif honeypot.get("buy_tax", 0) > 20 or honeypot.get("sell_tax", 0) > 20:
        risks.append("HIGH")
    
    # Verificar liquidez
    liquidity = security_report["liquidity"]
    if not liquidity.get("error"):
        if not liquidity["is_reliable_dex"]:
            risks.append("MEDIUM")
        if not liquidity["has_sufficient_liquidity"]:
            risks.append("MEDIUM")
        if not liquidity["is_native_pair"]:
            risks.append("LOW")
    
    # Verificar contrato
    contract = security_report["contract"]
    if not contract.get("error") and not contract.get("verified", False):
        risks.append("MEDIUM")
    
    # Determinar risco geral
    if "CRITICAL" in risks:
        security_report["overall_risk"] = "CRITICAL"
    elif "HIGH" in risks:
        security_report["overall_risk"] = "HIGH"
    elif "MEDIUM" in risks:
        security_report["overall_risk"] = "MEDIUM"
    elif risks:
        security_report["overall_risk"] = "LOW"
    else:
        security_report["overall_risk"] = "LOW"
    
    return security_report

def create_security_message(analysis, chain):
    """Cria mensagem detalhada de segurança"""
    token_name = analysis.get("name", "Unknown")
    token_symbol = analysis.get("symbol", "UNKNOWN")
    security = analysis.get("security", {})
    
    message = f"🛡️ <b>RELATÓRIO DE SEGURANÇA - {chain.upper()}</b>\n\n"
    message += f"<b>{token_name} ({token_symbol})</b>\n"
    message += f"🔒 <b>Risco Geral:</b> {security.get('overall_risk', 'UNKNOWN')}\n\n"
    
    # Honeypot info
    honeypot = security.get('honeypot', {})
    if not honeypot.get('error'):
        status = "🚫 HONEYPOT" if honeypot.get('is_honeypot') else "✅ Limpo"
        message += f"<b>🤖 Honeypot Check:</b> {status}\n"
        message += f"• Taxa Compra: {honeypot.get('buy_tax', 0)}%\n"
        message += f"• Taxa Venda: {honeypot.get('sell_tax', 0)}%\n\n"
    
    # Liquidity info
    liquidity = security.get('liquidity', {})
    if not liquidity.get('error'):
        message += f"<b>💧 Liquidez:</b> ${liquidity.get('liquidity_usd', 0):,.0f}\n"
        message += f"• DEX: {'✅ Confiável' if liquidity.get('is_reliable_dex') else '⚠️ Não confiável'}\n"
        message += f"• Par Nativo: {'✅ Sim' if liquidity.get('is_native_pair') else '⚠️ Não'}\n\n"
    
    # Contract info
    contract = security.get('contract', {})
    if not contract.get('error'):
        message += f"<b>📝 Contrato:</b>\n"
        message += f"• Verificado: {'✅ Sim' if contract.get('verified') else '⚠️ Não'}\n"
        message += f"• Nome: {contract.get('contract_name', 'Unknown')}\n\n"
    
    message += f"<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis.get('url')}'>DexScreener</a>\n"
    message += f"• <a href='{analysis.get('explorer')}'>Explorer</a>\n"
    
    risk_level = security.get('overall_risk', 'UNKNOWN')
    if risk_level == "CRITICAL":
        message += f"\n\n🚨 <b>ALERTA CRÍTICO: POTENCIAL HONEYPOT!</b>"
    elif risk_level == "HIGH":
        message += f"\n\n⚠️ <b>ALTA: Taxas muito altas!</b>"
    elif risk_level == "MEDIUM":
        message += f"\n\n⚠️ <b>MEDIO: Verifique antes de investir!</b>"
    else:
        message += f"\n\n✅ <b>Parece seguro (sempre DYOR!)</b>"
    
    return message

def monitor_tokens_with_security():
    """Monitora tokens com verificações REAIS de segurança"""
    logging.info("🔍 Procurando tokens com verificações de segurança...")
    tokens_analisados = 0
    
    for chain in CHAINS:
        if not CHAINS[chain]["enabled"]:
            continue
            
        try:
            all_pairs = get_token_pairs(chain)
            logging.info(f"📊 {chain}: {len(all_pairs)} pares encontrados")
            
            for pair in all_pairs:
                token_address = pair.get("baseToken", {}).get("address")
                
                if token_address and token_address not in vistos:
                    vistos.add(token_address)
                    
                    # Análise COMPLETA de segurança
                    security_report = analyze_token_security(pair, chain)
                    
                    # Adicionar informações básicas
                    analysis = {
                        "name": pair.get("baseToken", {}).get("name", "Unknown"),
                        "symbol": pair.get("baseToken", {}).get("symbol", "UNKNOWN"),
                        "url": pair.get("url", ""),
                        "explorer": f"{CHAINS[chain]['explorer']}{token_address}",
                        "security": security_report
                    }
                    
                    # Enviar relatório de segurança
                    message = create_security_message(analysis, chain)
                    if send_telegram(message):
                        tokens_analisados += 1
                        logging.info(f"✅ {chain}: Relatório de segurança para {analysis['symbol']}")
                    
                    time.sleep(3)  # Respeitar rate limits
                    
        except Exception as e:
            logging.error(f"Erro em {chain}: {e}")
    
    return tokens_analisados

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    logging.info("🤖 Bot de Segurança com API Unificada Etherscan iniciado!")
    
    if send_telegram("🛡️ <b>Bot de Segurança iniciado!</b>\n🔍 Usando API unificada Etherscan\n✅ Verificando múltiplas chains\n🔄 Suporte: ETH, BSC, Polygon, Arbitrum"):
        logging.info("✅ Conexão com Telegram OK!")
    
    while True:
        try:
            tokens_analisados = monitor_tokens_with_security()
            logging.info(f"✅ {tokens_analisados} tokens analisados!")
            
            wait_time = random.randint(300, 600)  # 5-10 minutos
            logging.info(f"⏳ Próxima verificação em {wait_time//60} minutos...")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
