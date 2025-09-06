"""
Diagnostic complet pour Ollama sur Windows
Vérifie service, ports, API HTTP et propose solutions
"""
import subprocess
import socket
import time
import requests
import psutil
from typing import Optional, Dict, Any
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OllamaDiagnostic:
    """Diagnostique et répare les problèmes courants d'Ollama"""
    
    DEFAULT_PORT = 11434
    DEFAULT_HOST = "127.0.0.1"
    
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        
    def check_port_availability(self) -> bool:
        """Vérifie si le port est disponible ou occupé"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex((self.host, self.port))
                return result == 0  # True = port occupé (bon signe si c'est Ollama)
        except Exception as e:
            logger.error(f"Erreur vérification port: {e}")
            return False
    
    def find_ollama_process(self) -> Optional[psutil.Process]:
        """Recherche le processus Ollama en cours"""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'ollama' in proc.info['name'].lower():
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None
    
    def check_ollama_api(self) -> Dict[str, Any]:
        """Teste l'API HTTP d'Ollama"""
        try:
            response = requests.get(f"{self.base_url}/api/version", timeout=2)
            if response.status_code == 200:
                return {"status": "ok", "version": response.json()}
            else:
                return {"status": "error", "code": response.status_code}
        except requests.exceptions.RequestException as e:
            return {"status": "error", "message": str(e)}
    
    def start_ollama_service(self) -> bool:
        """Démarre Ollama en mode serve (Windows)"""
        try:
            # Essai 1: Via PowerShell en background
            cmd = ["powershell", "-Command", "Start-Process", "ollama", "-ArgumentList", "'serve'", "-WindowStyle", "Hidden"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                # Essai 2: Direct avec subprocess
                subprocess.Popen(["ollama", "serve"], 
                               creationflags=subprocess.CREATE_NO_WINDOW,
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
            
            # Attendre le démarrage
            time.sleep(3)
            return True
            
        except Exception as e:
            logger.error(f"Impossible de démarrer Ollama: {e}")
            return False
    
    def diagnose_and_fix(self) -> Dict[str, Any]:
        """Diagnostic complet avec tentative de réparation"""
        report = {
            "port_check": False,
            "process_found": False,
            "api_status": None,
            "fix_attempted": False,
            "ready": False
        }
        
        # 1. Vérifier le port
        report["port_check"] = self.check_port_availability()
        logger.info(f"Port {self.port} {'occupé' if report['port_check'] else 'libre'}")
        
        # 2. Chercher le processus
        proc = self.find_ollama_process()
        report["process_found"] = proc is not None
        if proc:
            logger.info(f"Processus Ollama trouvé: PID {proc.pid}")
        else:
            logger.warning("Aucun processus Ollama détecté")
        
        # 3. Tester l'API
        api_result = self.check_ollama_api()
        report["api_status"] = api_result
        
        if api_result["status"] == "ok":
            logger.info("✅ Ollama API fonctionnelle")
            report["ready"] = True
        else:
            logger.warning("❌ API Ollama inaccessible")
            
            # 4. Tentative de démarrage si nécessaire
            if not report["process_found"]:
                logger.info("Tentative de démarrage d'Ollama...")
                if self.start_ollama_service():
                    report["fix_attempted"] = True
                    time.sleep(2)
                    
                    # Re-test après démarrage
                    api_result = self.check_ollama_api()
                    report["api_status"] = api_result
                    report["ready"] = api_result["status"] == "ok"
        
        return report

# Fonction utilitaire pour usage direct
def ensure_ollama_running() -> bool:
    """S'assure qu'Ollama est opérationnel"""
    diag = OllamaDiagnostic()
    result = diag.diagnose_and_fix()
    return result["ready"]

if __name__ == "__main__":
    diag = OllamaDiagnostic()
    report = diag.diagnose_and_fix()
    
    print("\n=== RAPPORT DE DIAGNOSTIC OLLAMA ===")
    print(f"Port {diag.port}: {'✓ Occupé' if report['port_check'] else '✗ Libre'}")
    print(f"Processus: {'✓ Trouvé' if report['process_found'] else '✗ Absent'}")
    print(f"API: {report['api_status']}")
    print(f"Statut final: {'✅ PRÊT' if report['ready'] else '❌ NON DISPONIBLE'}")
    
    if not report["ready"]:
        print("\n💡 Solutions suggérées:")
        print("1. Installer Ollama: winget install Ollama.Ollama")
        print("2. Démarrer manuellement: ollama serve")
        print("3. Vérifier pare-feu Windows pour port 11434")