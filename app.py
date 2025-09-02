import os
import requests
import time
import logging
import json
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)

# Configurações
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', '60'))  # segundos

# APIs
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex"
HONEYPOT_API = "https://api.honeypot.is/v2/IsHoneypot"

# Cadeias suportadas
CHAINS = {
    "ethereum": {
        "native_token": "0x2170ed0880ac9a755fd29b2688956bd959f933f8",
        "explorer": "https://etherscan.io/token/",
        "symbol": "ETH"
    },
    "bsc": {
        "native_token": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "explorer": "https://bscscan.com/token/",
        "symbol": "BNB"
    },
    "polygon": {
        "native_token": "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270",
        "explorer": "https://polygonscan.com/token/",
        "symbol": "MATIC"
    },
    "arbitrum": {
        "native_token": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
        "explorer": "https://arbiscan.io/token/",
        "symbol": "ETH"
    }
}

# Sistema de arquivos para persistência
DATA_FILE = "bot_data.json"

class TokenMonitor:
    def __init__(self):
        self.vistos = self.load_data()
        self.scheduler = BackgroundScheduler()
        self.setup_scheduler()
        
    def load_data(self):
        """Carrega dados persistentes"""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f:
                    return set(json.load(f))
        except Exception as e:
            logging.error(f"Erro ao carregar dados: {e}")
        return set()
    
    def save_data(self):
        """Salva dados persistentes"""
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(list(self.vistos), f)
        except Exception as e:
            logging.error(f"Erro ao salvar dados: {e}")
    
    def send_telegram(self, msg):
        """Envia mensagem para o Telegram"""
        if not TELEGRAM_TOKEN or not CHAT_ID:
            logging.error("Token ou Chat ID não configurado!")
            return False
            
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID, 
            "text": msg, 
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logging.info("✅ Mensagem enviada com sucesso!")
            return True
        except Exception as e:
            logging.error(f"❌ Erro ao enviar mensagem Telegram: {e}")
            return False
    
    def get_recent_pairs(self, chain):
        """Busca pares recentes de uma chain específica"""
        native_token = CHAINS[chain]["native_token"]
        url = f"{DEXSCREENER_API}/tokens/{native_token}"
        
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Filtrar pares recentes (últimas 2 horas)
            recent_pairs = []
            for pair in data.get("pairs", []):
                created_at = pair.get("pairCreatedAt", 0)
                if created_at and (time.time() * 1000 - created_at) < 7200000:  # 2 horas
                    recent_pairs.append(pair)
            
            return recent_pairs[:20]  # Limitar a 20 pares
        except Exception as e:
            logging.error(f"❌ Erro ao buscar pares {chain}: {e}")
            return []
    
    def check_honeypot(self, chain, contract):
        """Verifica se é honeypot e retorna score"""
        try:
            url = f"{HONEYPOT_API}?chain={chain}&token={contract}"
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            data = response.json()
            
            simulation = data.get("simulation", {})
            if simulation.get("isHoneypot", False):
                return 0, "🚫 Honeypot detectado!"
            
            buy_tax = simulation.get("buyTax", 0)
            sell_tax = simulation.get("sellTax", 0)
            
            if buy_tax < 5 and sell_tax < 5:
                return 25, "✅ Taxas baixas"
            elif buy_tax < 10 and sell_tax < 10:
                return 20, "⚠️ Taxas moderadas"
            elif buy_tax < 20 and sell_tax < 20:
                return 10, "⚠️ Taxas altas"
            else:
                return 0, "❌ Taxas muito altas"
                
        except Exception as e:
            logging.error(f"❌ Erro Honeypot {contract}: {e}")
            return 15, "⚠️ Não foi possível verificar honeypot"
    
    def score_liquidity(self, liquidity_usd):
        """Calcula score baseado na liquidez"""
        if liquidity_usd > 100000:
            return 30, "💰 Liquidez excelente"
        elif liquidity_usd > 50000:
            return 25, "💧 Liquidez boa"
        elif liquidity_usd > 20000:
            return 15, "💧 Liquidez moderada"
        elif liquidity_usd > 5000:
            return 5, "💧 Liquidez baixa"
        else:
            return 0, "❌ Liquidez muito baixa"
    
    def score_volume(self, volume_24h):
        """Calcula score baseado no volume"""
        if volume_24h > 200000:
            return 20, "📈 Volume excelente"
        elif volume_24h > 100000:
            return 15, "📈 Volume bom"
        elif volume_24h > 50000:
            return 10, "📈 Volume moderado"
        elif volume_24h > 10000:
            return 5, "📈 Volume baixo"
        else:
            return 0, "❌ Volume muito baixo"
    
    def score_holders(self, holders_count):
        """Calcula score baseado em holders"""
        if not holders_count or holders_count < 10:
            return 0, "❌ Poucos holders"
        elif holders_count < 50:
            return 5, "👥 Holders moderados"
        elif holders_count < 100:
            return 10, "👥 Holders bons"
        else:
            return 15, "👥 Muitos holders"
    
    def score_age(self, created_timestamp):
        """Calcula score baseado na idade do token"""
        if not created_timestamp:
            return 5, "⏰ Idade desconhecida"
        
        age_hours = (time.time() * 1000 - created_timestamp) / 3600000
        
        if age_hours < 1:
            return 15, "🆕 Token muito novo (<1h)"
        elif age_hours < 6:
            return 10, "🆕 Token novo (<6h)"
        elif age_hours < 24:
            return 5, "⏰ Token recente (<24h)"
        else:
            return 0, "⏰ Token antigo"
    
    def analyze_token(self, pair, chain):
        """Analisa um token e retorna score detalhado"""
        base_token = pair.get("baseToken", {})
        quote_token = pair.get("quoteToken", {})
        
        token_address = base_token.get("address")
        token_name = base_token.get("name", "Unknown")
        token_symbol = base_token.get("symbol", "UNKNOWN")
        
        liquidity = pair.get("liquidity", {}).get("usd", 0)
        volume_24h = pair.get("volume", {}).get("h24", 0)
        created_at = pair.get("pairCreatedAt")
        
        # Scores individuais
        scores = []
        details = []
        
        # Liquidez
        liq_score, liq_detail = self.score_liquidity(liquidity)
        scores.append(liq_score)
        details.append(liq_detail)
        
        # Volume
        vol_score, vol_detail = self.score_volume(volume_24h)
        scores.append(vol_score)
        details.append(vol_detail)
        
        # Honeypot check
        honeypot_score, honeypot_detail = self.check_honeypot(chain, token_address)
        scores.append(honeypot_score)
        details.append(honeypot_detail)
        
        # Idade do token
        age_score, age_detail = self.score_age(created_at)
        scores.append(age_score)
        details.append(age_detail)
        
        total_score = sum(scores)
        
        return {
            "address": token_address,
            "name": token_name,
            "symbol": token_symbol,
            "liquidity": liquidity,
            "volume_24h": volume_24h,
            "created_at": created_at,
            "score": total_score,
            "max_score": 100,
            "details": details,
            "dex_url": pair.get("url", ""),
            "explorer_url": f"{CHAINS[chain]['explorer']}{token_address}"
        }
    
    def create_message(self, analysis, chain):
        """Cria mensagem formatada para Telegram"""
        emoji = "🟢" if analysis["score"] >= 60 else "🟡" if analysis["score"] >= 40 else "🔴"
        
        message = f"{emoji} <b>NOVO TOKEN {chain.upper()}</b>\n\n"
        message += f"<b>🏷 {analysis['name']} ({analysis['symbol']})</b>\n"
        message += f"<b>⭐ Score:</b> {analysis['score']}/100\n\n"
        
        message += f"<b>📊 Estatísticas:</b>\n"
        message += f"💧 <b>Liquidez:</b> ${analysis['liquidity']:,.0f}\n"
        message += f"📈 <b>Volume 24h:</b> ${analysis['volume_24h']:,.0f}\n\n"
        
        message += f"<b>🔍 Análise:</b>\n"
        for detail in analysis["details"]:
            message += f"• {detail}\n"
        
        message += f"\n<b>🔗 Links:</b>\n"
        message += f"• <a href='{analysis['dex_url']}'>DexScreener</a>\n"
        message += f"• <a href='{analysis['explorer_url']}'>Explorer</a>"
        
        return message
    
    def check_tokens(self):
        """Verifica tokens em todas as chains"""
        logging.info("🔍 Iniciando verificação de tokens...")
        
        for chain in CHAINS.keys():
            try:
                pairs = self.get_recent_pairs(chain)
                logging.info(f"📊 Encontrados {len(pairs)} pares em {chain}")
                
                for pair in pairs:
                    pair_address = pair.get("pairAddress")
                    
                    if pair_address and pair_address not in self.vistos:
                        self.vistos.add(pair_address)
                        
                        # Analisar token
                        analysis = self.analyze_token(pair, chain)
                        
                        # Só enviar se score for razoável
                        if analysis["score"] >= 40:
                            message = self.create_message(analysis, chain)
                            self.send_telegram(message)
                            
                            logging.info(f"✅ Token {analysis['symbol']} enviado (Score: {analysis['score']})")
                        else:
                            logging.info(f"⏭ Token {analysis['symbol']} ignorado (Score: {analysis['score']})")
                
            except Exception as e:
                logging.error(f"❌ Erro ao processar {chain}: {e}")
        
        # Salvar dados
        self.save_data()
        logging.info("✅ Verificação concluída!")
    
    def setup_scheduler(self):
        """Configura o agendador de tarefas"""
        self.scheduler.add_job(
            self.check_tokens,
            'interval',
            minutes=2,
            id='token_check',
            replace_existing=True
        )
    
    def start(self):
        """Inicia o monitor"""
        if not TELEGRAM_TOKEN or not CHAT_ID:
            logging.error("❌ Configure TELEGRAM_TOKEN e CHAT_ID!")
            return False
        
        logging.info("🤖 Iniciando Token Monitor Bot...")
        self.send_telegram("🤖 <b>Token Monitor iniciado!</b>\n🔍 Monitorando tokens nas redes...")
        
        # Primeira verificação imediata
        self.check_tokens()
        
        # Iniciar agendador
        self.scheduler.start()
        logging.info("✅ Agendador iniciado!")
        
        return True
    
    def run(self):
        """Loop principal"""
        try:
            if self.start():
                # Manter o script rodando
                while True:
                    time.sleep(3600)  # Dormir por 1 hora
        except KeyboardInterrupt:
            logging.info("⏹ Parando bot...")
            self.scheduler.shutdown()
            self.save_data()
        except Exception as e:
            logging.error(f"❌ Erro fatal: {e}")
            self.send_telegram("❌ <b>Bot parado devido a erro!</b>")

# Função principal
def main():
    monitor = TokenMonitor()
    monitor.run()

if __name__ == "__main__":
    main()
