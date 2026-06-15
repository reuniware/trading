"""
Gestion des risques : sizing, limites de perte, R:R, drawdown.
"""

import logging
from typing import Optional, Tuple
from dataclasses import dataclass

import MetaTrader5 as mt5

from .config import RISK
from .mt5_connector import MT5Connector

logger = logging.getLogger("RiskManager")


@dataclass
class PositionSizingResult:
    lots: float
    risk_amount: float
    risk_percent: float
    reward_amount: float
    rr_ratio: float
    method: str


class RiskManager:
    """Gère le sizing des positions et les limites de risque."""

    def __init__(self):
        self.mt5 = MT5Connector()

    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        risk_percent: Optional[float] = None,
        method: Optional[str] = None,
    ) -> Optional[PositionSizingResult]:
        """
        Calcule la taille de position basée sur le risque.
        Méthodes: fixed_risk, fixed_lot

        Retourne le nombre de lots à ouvrir.
        """
        if not self.mt5.ensure_connected():
            return None

        method = method or RISK.position_sizing_method
        risk_pct = risk_percent or RISK.max_risk_percent

        # Infos du compte
        account = self.mt5.get_account_info()
        if not account:
            logger.error("Impossible de récupérer les infos du compte")
            return None

        balance = account.get("balance", 0)
        equity = account.get("equity", 0)
        risk_amount = balance * risk_pct / 100.0

        # Distance SL (en pips/points)
        sl_distance = abs(entry_price - stop_loss)

        if sl_distance == 0:
            logger.error("Distance SL = 0, impossible de calculer le sizing")
            return None

        # Infos du symbole
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return None

        tick_value = symbol_info.trade_tick_value
        tick_size = symbol_info.trade_tick_size
        contract_size = symbol_info.trade_contract_size

        # Calcul lots
        if method == "fixed_lot":
            lots = RISK.default_lot_size
            risk_amt = self._calculate_risk_amount(symbol, lots, sl_distance, tick_value, tick_size)
            risk_pct_actual = risk_amt / balance * 100 if balance > 0 else 0
        else:
            # fixed_risk (par défaut)
            risk_per_unit = tick_value * (sl_distance / tick_size)
            if risk_per_unit > 0:
                lots = risk_amount / (risk_per_unit * contract_size)
                lots = self._round_lots(symbol, lots)
            else:
                lots = RISK.default_lot_size

            risk_amt = risk_amount

        # Calcul du R:R (basé sur les TP potentiels)
        reward_amt = risk_amt * RISK.default_r_multiple
        rr_ratio = RISK.default_r_multiple

        # Vérification des limites
        lots = min(lots, symbol_info.volume_max or lots)
        lots = max(lots, symbol_info.volume_min or 0.01)

        risk_pct_actual = risk_amt / balance * 100 if balance > 0 else 0

        return PositionSizingResult(
            lots=round(lots, 2),
            risk_amount=round(risk_amt, 2),
            risk_percent=round(risk_pct_actual, 2),
            reward_amount=round(reward_amt, 2),
            rr_ratio=rr_ratio,
            method=method,
        )

    def _calculate_risk_amount(
        self, symbol: str, lots: float, sl_distance: float,
        tick_value: float, tick_size: float
    ) -> float:
        """Calcule le montant risqué pour une taille de lots donnée."""
        risk_per_unit = tick_value * (sl_distance / tick_size)
        return risk_per_unit * lots

    def _round_lots(self, symbol: str, lots: float) -> float:
        """Arrondit le lot à la valeur autorisée par le broker."""
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return round(lots, 2)
        lot_step = symbol_info.volume_step or 0.01
        return round(round(lots / lot_step) * lot_step, 2)

    def check_daily_loss_limit(self) -> bool:
        """
        Vérifie si la limite de perte quotidienne est atteinte.
        Retourne True si on peut trader, False si la limite est dépassée.
        """
        if not self.mt5.ensure_connected():
            return False

        account = self.mt5.get_account_info()
        if not account:
            return True

        balance = account.get("balance", 0)
        equity = account.get("equity", 0)
        daily_loss = balance - equity

        # Perte en % du solde
        if balance > 0:
            loss_pct = daily_loss / balance * 100
        else:
            loss_pct = 0

        if loss_pct >= RISK.max_daily_loss_percent:
            logger.warning(
                "⚠️ Limite de perte journalière atteinte: %.2f%% (max: %.1f%%)",
                loss_pct, RISK.max_daily_loss_percent
            )
            return False

        return True

    def check_open_positions_limit(self) -> bool:
        """Vérifie si on peut ouvrir une nouvelle position."""
        if not self.mt5.ensure_connected():
            return False

        positions = mt5.positions_get()
        if positions is None:
            return True

        return len(positions) < RISK.max_open_positions

    def calculate_rr(self, entry: float, stop: float, target: float, direction: str) -> float:
        """Calcule le ratio Risk:Reward."""
        if direction == "buy":
            risk = entry - stop
            reward = target - entry
        else:
            risk = stop - entry
            reward = entry - target

        if risk <= 0:
            return 0.0

        return round(reward / risk, 2)

    def validate_trade(self, signal) -> Tuple[bool, str]:
        """Valide un trade avant exécution."""
        if not self.check_daily_loss_limit():
            return False, "Limite de perte journalière atteinte"

        if not self.check_open_positions_limit():
            return False, "Nombre max de positions atteint"

        if signal.stop_loss <= 0:
            return False, "Stop loss invalide"

        # Vérifier R:R
        rr = self.calculate_rr(
            signal.entry_zone_high if signal.direction == "buy" else signal.entry_zone_low,
            signal.stop_loss,
            signal.target_1,
            signal.direction,
        )
        if rr < RISK.min_r_multiple:
            return False, f"R:R insuffisant ({rr:.1f} < {RISK.min_r_multiple})"

        return True, "Trade validé"
