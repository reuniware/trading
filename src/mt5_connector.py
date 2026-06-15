"""
Gestionnaire de connexion MetaTrader 5.
Singleton avec auto-reconnect et logging.
"""

import time
import logging
from typing import Optional
import MetaTrader5 as mt5

logger = logging.getLogger("MT5Connector")


class MT5Connector:
    """Connexion singleton à MetaTrader 5."""

    _instance: Optional["MT5Connector"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, terminal_path: Optional[str] = None):
        if not self._initialized:
            self.terminal_path = terminal_path or (
                r"C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe"
            )
            self._initialized = True

    def initialize(self, retries: int = 3, delay: float = 2.0) -> bool:
        """Initialise la connexion MT5 avec tentatives."""
        for attempt in range(1, retries + 1):
            if self.is_connected():
                logger.info("Deja connecte a MT5.")
                return True

            # Ne passer que le path - les login/password/server=None forcent
            # MT5 a tenter un login invalide. On laisse MT5 se connecter
            # au terminal deja ouvert.
            initialized = mt5.initialize(path=self.terminal_path)

            if initialized:
                logger.info("[OK] Connecte a MT5 (tentative %d/%d)", attempt, retries)
                return True

            error = mt5.last_error()
            logger.warning("[FAIL] Connexion MT5 (tentative %d/%d): %s", attempt, retries, error)
            if attempt < retries:
                time.sleep(delay)

        return False

    def is_connected(self) -> bool:
        """Vérifie si MT5 est connecté."""
        return mt5.terminal_info() is not None

    def ensure_connected(self) -> bool:
        """S'assure que la connexion est active, reconnecte si nécessaire."""
        if not self.is_connected():
            logger.info("Reconnexion à MT5...")
            return self.initialize()
        return True

    def shutdown(self):
        """Ferme proprement la connexion."""
        try:
            mt5.shutdown()
            logger.info("Connexion MT5 fermée.")
        except Exception as e:
            logger.warning("Erreur à la fermeture MT5: %s", e)
        finally:
            self._initialized = False

    @staticmethod
    def last_error() -> tuple:
        """Retourne la dernière erreur MT5."""
        return mt5.last_error()

    def get_terminal_info(self) -> Optional[dict]:
        """Infos sur le terminal."""
        if not self.ensure_connected():
            return None
        info = mt5.terminal_info()
        if info:
            return info._asdict()
        return None

    def get_account_info(self) -> Optional[dict]:
        """Infos sur le compte de trading."""
        if not self.ensure_connected():
            return None
        info = mt5.account_info()
        if info:
            return info._asdict()
        return None

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, *args):
        self.shutdown()
