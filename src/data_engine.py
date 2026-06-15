"""
Moteur de données multi-timeframes.
Récupère et met en cache les données OHLC de MT5.
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import MetaTrader5 as mt5

from .config import TIMEFRAMES, TIMEFRAME_BARS, TIMEFRAME_HIERARCHY, TIMEFRAME_NAMES
from .mt5_connector import MT5Connector

logger = logging.getLogger("DataEngine")


class DataEngine:
    """Gère la récupération et la mise en cache des données OHLC multi-TF."""

    def __init__(self):
        self.mt5 = MT5Connector()
        self._cache: Dict[str, Dict[str, pd.DataFrame]] = {}  # {symbol: {tf: df}}
        self._cache_timestamps: Dict[str, Dict[str, float]] = {}
        self._cache_ttl: float = 10.0  # secondes avant refresh

    def _check_cache(self, symbol: str, tf_name: str) -> Optional[pd.DataFrame]:
        """Vérifie si le cache est encore valide."""
        if symbol in self._cache and tf_name in self._cache[symbol]:
            ts = self._cache_timestamps.get(symbol, {}).get(tf_name, 0)
            if time.time() - ts < self._cache_ttl:
                return self._cache[symbol][tf_name]
        return None

    def _update_cache(self, symbol: str, tf_name: str, df: pd.DataFrame):
        """Met à jour le cache."""
        if symbol not in self._cache:
            self._cache[symbol] = {}
            self._cache_timestamps[symbol] = {}
        self._cache[symbol][tf_name] = df
        self._cache_timestamps[symbol][tf_name] = time.time()

    def clear_cache(self, symbol: Optional[str] = None):
        """Vide le cache."""
        if symbol:
            self._cache.pop(symbol, None)
            self._cache_timestamps.pop(symbol, None)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()

    def set_cache_ttl(self, ttl: float):
        """Change la durée de vie du cache."""
        self._cache_ttl = ttl

    def fetch_rates(
        self,
        symbol: str,
        tf_name: str,
        count: Optional[int] = None,
        force: bool = False,
    ) -> Optional[pd.DataFrame]:
        """
        Récupère les données OHLC pour un symbole et timeframe donné.
        Retourne un DataFrame avec colonnes: time, open, high, low, close, tick_volume, spread, real_volume.
        """
        if tf_name not in TIMEFRAMES:
            logger.error("Timeframe inconnu: %s", tf_name)
            return None

        if not force:
            cached = self._check_cache(symbol, tf_name)
            if cached is not None:
                return cached

        if not self.mt5.ensure_connected():
            logger.error("Impossible de se connecter à MT5 pour récupérer les données %s %s", symbol, tf_name)
            return None

        tf = TIMEFRAMES[tf_name]
        bars = count or TIMEFRAME_BARS.get(tf_name, 500)

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
        if rates is None or len(rates) == 0:
            logger.warning("Aucune donnée pour %s %s", symbol, tf_name)
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)

        # Nettoyage
        df.drop(columns=["spread", "real_volume"], inplace=True, errors="ignore")

        self._update_cache(symbol, tf_name, df)
        return df

    def fetch_all_timeframes(
        self, symbol: str, force: bool = False,
        timeframes: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Récupère les données pour un symbole sur les timeframes demandés.
        Si timeframes est None, tous les timeframes sont chargés.
        """
        result = {}
        tfs = timeframes if timeframes is not None else TIMEFRAME_NAMES
        for tf_name in tfs:
            if tf_name not in TIMEFRAMES:
                continue
            df = self.fetch_rates(symbol, tf_name, force=force)
            if df is not None:
                result[tf_name] = df
        return result

    def fetch_rates_range(
        self,
        symbol: str,
        tf_name: str,
        from_date: datetime,
        to_date: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """Récupère les données sur une plage de dates."""
        if tf_name not in TIMEFRAMES:
            return None

        if not self.mt5.ensure_connected():
            return None

        tf = TIMEFRAMES[tf_name]
        to_date = to_date or datetime.now()

        rates = mt5.copy_rates_range(symbol, tf, from_date, to_date)
        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.drop(columns=["spread", "real_volume"], inplace=True, errors="ignore")
        return df

    def get_latest_price(self, symbol: str) -> Optional[dict]:
        """Récupère le dernier tick/prix."""
        if not self.mt5.ensure_connected():
            return None
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            return {
                "bid": tick.bid,
                "ask": tick.ask,
                "spread": tick.ask - tick.bid,
                "time": datetime.fromtimestamp(tick.time),
                "last": tick.last,
                "volume": tick.volume,
            }
        return None

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """Infos détaillées sur un symbole."""
        if not self.mt5.ensure_connected():
            return None
        info = mt5.symbol_info(symbol)
        if info:
            return info._asdict()
        return None

    @staticmethod
    def get_higher_timeframe(tf_name: str) -> Optional[str]:
        """Retourne le TF supérieur dans la hiérarchie."""
        idx = TIMEFRAME_HIERARCHY.index(tf_name) if tf_name in TIMEFRAME_HIERARCHY else -1
        if idx > 0:
            return TIMEFRAME_HIERARCHY[idx - 1]
        return None

    @staticmethod
    def get_lower_timeframes(tf_name: str) -> List[str]:
        """Retourne les TF inférieurs dans la hiérarchie."""
        idx = TIMEFRAME_HIERARCHY.index(tf_name) if tf_name in TIMEFRAME_HIERARCHY else -1
        if idx >= 0 and idx < len(TIMEFRAME_HIERARCHY) - 1:
            return TIMEFRAME_HIERARCHY[idx + 1:]
        return []
