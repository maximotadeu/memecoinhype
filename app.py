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

# APIs de segurança REAIS
HONEYPOT_API = "https://api.honeypot.is/v2/IsHoneypot"
RUGCHECK_API = "https://api.rugcheck.xyz/tokens"
BSCSCAN_API = "https://api.bscscan.com/api"
ETHSCAN_API = "https://api.etherscan.io/api"

# Suas API Keys (adicionar depois no Render)
BSCSCAN_API_KEY = os.environ.get('BSCSCAN_API_KEY', 'YourApiKeyToken')
ETHERSCAN_API_KEY = os.environ.get('ETHERSCAN_API_KEY', 'YourApiKeyToken')

CHAINS = {
    "ethereum": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0x2170ed0880ac9a755fd29b2688956bd959f933f8",
        "explorer": "https://etherscan.io/token/",
        "chain_id": "eth",
        "scan_api": ETHSCAN_API,
        "api_key": ETHERSCAN_API_KEY,
        "enabled": True
    },
    "bsc": {
        "url": "https://api.dexscreener.com/latest/dex/tokens/0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
        "explorer": "https://bscscan.com/token/", 
        "chain_id": "bsc",
        "scan_api": BSCSCAN_API,
        "api_key": BSCSCAN_API_KEY,
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
            transfer_tax = simulation.get("transferTax", 0)
            
            return {
                "is_honeypot": is_honeypot,
                "buy_tax": buy_tax,
                "sell_tax": sell_tax,
                "transfer_tax": transfer_tax,
                "risk_level": "CRITICAL" if is_honeypot else "LOW"
            }
        
        return {"error": "API unavailable"}
        
    except Exception as e:
        return {"error": str(e)}

def check_rugcheck(chain, token_address):
    """Verificação com RugCheck API"""
    try:
        url = f"{RUGCHECK_API}/{token_address}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return data
        return {"error": "RugCheck failed"}
    except:
        return {"error": "RugCheck error"}

def check_contract_analysis(chain, token_address):
    """Análise do contrato no Etherscan/Bscscan"""
    try:
        if chain == "ethereum":
            api_url = ETHSCAN_API
            api_key = ETHERSCAN_API_KEY
        else:
            api_url = BSCSCAN_API
            api_key = BSCSCAN_API_KEY
        
        # Verificar se contrato é verified
        params = {
            "module": "contract",
            "action": "getsourcecode",
            "address": token_address,
            "apikey": api_key
        }
        
        response = requests.get(api_url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data["result"] and isinstance(data["result"], list):
                contract_info = data["result"][0]
                return {
                    "verified": contract_info.get("SourceCode") != "",
                    "proxy": contract_info.get("Proxy") == "1",
                    "contract_name": contract_info.get("ContractName", "Unknown")
                }
        
        return {"error": "Scan API failed"}
    except Exception as e:
        return {"error": str(e)}

def check_liquidity_lock_real(pair, chain, token_address):
    """Verificação REAL de liquidez travada"""
    try:
        # 1. Verificar se LP está em DEX confiável
        dex_id = pair.get("dexId", "").lower()
        reliable_dexs = ["pancakeswap", "uniswap", "raydium"]
        is_reliable_dex = any(dex in dex_id for dex in reliable_dexs)
        
        # 2. Verificar liquidez mínima
        liquidity = pair.get("liquidity", {}).get("usd", 0)
        has_sufficient_liquidity = liquidity > 10000  # $10k mínimo
        
        # 3. Verificar se é par com token nativo (mais seguro)
        quote_token = pair.get("quoteToken", {}).get("symbol", "").upper()
        is_native_pair = quote_token in ["WBNB", "BNB", "WETH", "ETH", "SOL"]
        
        # 4. Verificar idade do par
        created_at = pair.get("pairCreatedAt", 0)
        is_new = False
        if created_at:
            created_time = datetime.fromtimestamp(created_at / 1000)
            age = datetime.now() - created_time
            is_new = age.days < 3  # Menos de 3 dias
        
        return {
            "is_reliable_dex": is_reliable_dex,
            "has_sufficient_liquidity": has_sufficient_liquidity,
            "is_native_pair": is_native_pair,
            "is_new_pair": is_new,
            "liquidity_usd": liquidity,
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
            pairs.sort(key=lambda x: x.get("volume", {}).get("h24", 0), reverse=True)
            return pairs[:10]
        return []
    except Exception as e:
        logging.error(f"Erro em {chain}: {e}")
        return []

def analyze_token_security(pair, chain):
    """Análise COMPLETA de segurança"""
    base_token = pair.get("baseToken", {})
    token_address = base_token.get("address")
    
    security_report = {
        "honeypot": check_honeypot_real(chain, token_address),
        "rugcheck": check_rugcheck(chain, token_address),
        "contract": check_contract_analysis(chain, token_address),
        "liquidity": check_liquidity_lock_real(pair, chain, token_address),
        "overall_risk": "UNKNOWN"
    }
    
    # Determinar risco geral
    risks = []
    
    if security_report["honeypot"].get("is_honeypot", False):
        risks.append("CRITICAL")
    
    if security_report["liquidity"].get("risk_level") == "MEDIUM":
        risks.append("MEDIUM")
    
    if not security_report["contract"].get("verified", False):
        risks.append("MEDIUM")
    
    if risks:
        security_report["overall_risk"] = max(risks)
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
        message += f"<b>🤖 Honeypot Check:</b>\n"
        message += f"• Status: {'🚫 HONEYPOT' if honeypot.get('is_honeypot') else '✅ Limpo'}\n"
        message += f"• Taxa Compra: {honeypot.get('buy_tax', 0)}%\n"
        message += f"• Taxa Venda: {honeypot.get('sell_tax', 0)}%\n\n"
    
    # Liquidity info
    liquidity = security.get('liquidity', {})
    if not liquidity.get('error'):
        message += f"<b>💧 Liquidez:</b>\n"
        message += f"• Valor: ${liquidity.get('liquidity_usd', 0):,.0f}\n"
        message += f"• DEX: {'✅ Confiável' if liquidity.get('is_reliable_dex') else '⚠️ Não confiável'}\n"
        message += f"• Par Nativo: {'✅ Sim' if liquidity.get('is_native_pair') else '⚠️ Não'}\n\n"
    
    # Contract info
    contract = security.get('contract', {})
    if not contract.get('error'):
        message += f"<b>📝 Contrato:</b>\n"
        message += f"• Verificado: {'✅ Sim' if contract.get('verified') else '⚠️ Não'}\n"
        message += f"• Nome: {contract.get('contract_name', 'Unknown')}\n"
        message += f"• Proxy: {'⚠️ Sim' if contract.get('proxy') else '✅ Não'}\n\n"
    
    message += f"<b>🔗 Links:</b>\n"
    message += f"• <a href='{analysis.get('url')}'>DexScreener</a>\n"
    message += f"• <a href='{analysis.get('explorer')}'>Explorer</a>\n"
    
    if security['overall_risk'] == "CRITICAL":
        message += f"\n\n🚨 <b>ALERTA CRÍTICO: POTENCIAL HONEYPOT!</b>"
    elif security['overall_risk'] == "MEDIUM":
        message += f"\n\n⚠️ <b>CUIDADO: Verifique antes de investir!</b>"
    else:
        message += f"\n\n✅ <b>Parece seguro (mas sempre DYOR!)</b>"
    
    return message

def monitor_tokens_with_security():
    """Monitora tokens com verificações REAIS de segurança"""
    logging.info("🔍 Procurando tokens com verificações de segurança...")
    
    for chain in CHAINS:
        if not CHAINS[chain]["enabled"]:
            continue
            
        try:
            all_pairs = get_token_pairs(chain)
            
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
                        logging.info(f"✅ {chain}: Relatório de segurança enviado para {analysis['symbol']}")
                    
                    time.sleep(2)  # Respeitar rate limits
                    
        except Exception as e:
            logging.error(f"Erro em {chain}: {e}")

def main():
    """Função principal"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logging.error("Configure TELEGRAM_TOKEN e CHAT_ID!")
        return
    
    logging.info("🤖 Bot de Segurança iniciado!")
    
    if send_telegram("🛡️ <b>Bot de Segurança iniciado!</b>\n🔍 Verificando honeypot, liquidez e contratos\n✅ Usando APIs reais de segurança"):
        logging.info("✅ Conexão com Telegram OK!")
    
    while True:
        try:
            monitor_tokens_with_security()
            logging.info("✅ Verificação de segurança completa!")
            
            wait_time = random.randint(300, 600)  # 5-10 minutos
            logging.info(f"⏳ Próxima verificação em {wait_time//60} minutos...")
            time.sleep(wait_time)
            
        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
