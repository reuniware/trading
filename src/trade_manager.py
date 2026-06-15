"""
Gestionnaire d'ordres : passage, modification et clôture de positions MT5.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Tuple

import MetaTrader5 as mt5

from .mt5_connector import MT5Connector
from .risk_manager import RiskManager
from .signal_generator import TradeSignal

logger = logging.getLogger("TradeManager")


class TradeManager:
    """Gère l'exécution des trades sur MT5."""

    def __init__(self):
        self.mt5 = MT5Connector()
        self.risk = RiskManager()

    def place_order(
        self,
        symbol: str,
        direction: str,
        lots: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "ICT Signal",
        magic: int = 202606,
    ) -> Optional[Dict]:
        """
        Place un ordre market ou pending.

        Retourne le résultat de l'ordre.
        """
        if not self.mt5.ensure_connected():
            logger.error("MT5 non connecté")
            return None

        order_type = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL

        # Préparation de la requête
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lots,
            "type": order_type,
            "price": price or self._get_current_price(symbol, direction),
            "deviation": 10,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if stop_loss:
            request["sl"] = stop_loss
        if take_profit:
            request["tp"] = take_profit

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(
                "✅ Ordre exécuté: %s %s %.2f lots à %.2f",
                direction.upper(), symbol, lots, result.price
            )
            return {
                "order": result.order,
                "price": result.price,
                "volume": result.volume,
                "comment": comment,
                "time": datetime.now(),
            }
        else:
            error = result.comment if result else "Erreur inconnue"
            logger.error("❌ Échec ordre %s %s: %s", direction, symbol, error)
            return None

    def place_signal_order(
        self, signal: TradeSignal, lots: Optional[float] = None
    ) -> Optional[Dict]:
        """Place un ordre basé sur un signal ICT avec gestion de risque."""
        # Calcul du sizing
        entry_price = signal.entry_zone_high if signal.direction == "buy" else signal.entry_zone_low

        sizing = self.risk.calculate_position_size(
            signal.symbol, entry_price, signal.stop_loss
        )
        if not sizing:
            logger.error("Impossible de calculer le sizing")
            return None

        actual_lots = lots or sizing.lots

        # Validation
        valid, message = self.risk.validate_trade(signal)
        if not valid:
            logger.warning("Trade non validé: %s", message)
            return None

        # Ordre
        comment = f"ICT {signal.direction.upper()} S{signal.score:.0f}"
        return self.place_order(
            symbol=signal.symbol,
            direction=signal.direction,
            lots=actual_lots,
            stop_loss=signal.stop_loss,
            take_profit=signal.target_1,
            comment=comment,
        )

    def _get_current_price(self, symbol: str, direction: str) -> float:
        """Récupère le prix actuel (bid pour vente, ask pour achat)."""
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            return tick.ask if direction == "buy" else tick.bid
        return 0.0

    def modify_position(
        self,
        ticket: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> bool:
        """Modifie le SL/TP d'une position existante."""
        position = mt5.positions_get(ticket=ticket)
        if not position or len(position) == 0:
            logger.warning("Position %d introuvable", ticket)
            return False

        pos = position[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": pos.symbol,
        }
        if stop_loss is not None:
            request["sl"] = stop_loss
        if take_profit is not None:
            request["tp"] = take_profit

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info("✅ Position %d modifiée", ticket)
            return True
        else:
            logger.error("❌ Échec modification %d: %s", ticket, result.comment if result else "?")
            return False

    def close_position(self, ticket: int) -> bool:
        """Ferme une position."""
        position = mt5.positions_get(ticket=ticket)
        if not position or len(position) == 0:
            logger.warning("Position %d introuvable", ticket)
            return False

        pos = position[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        close_price = mt5.symbol_info_tick(pos.symbol).bid if close_type == mt5.ORDER_TYPE_SELL else mt5.symbol_info_tick(pos.symbol).ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": close_price,
            "deviation": 10,
            "magic": pos.magic,
            "comment": "CT Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info("✅ Position %d fermée", ticket)
            return True
        else:
            logger.error("❌ Échec fermeture %d: %s", ticket, result.comment if result else "?")
            return False

    def close_all_positions(self, symbol: Optional[str] = None) -> int:
        """Ferme toutes les positions, optionnellement filtrées par symbole."""
        positions = mt5.positions_get()
        if not positions:
            return 0

        count = 0
        for pos in positions:
            if symbol and pos.symbol != symbol:
                continue
            if self.close_position(pos.ticket):
                count += 1

        return count

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """Liste les positions ouvertes."""
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if not positions:
            return []

        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "buy" if pos.type == 0 else "sell",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "sl": pos.sl,
                "tp": pos.tp,
                "price_current": pos.price_current,
                "profit": pos.profit,
                "swap": pos.swap,
                "comment": pos.comment,
                "magic": pos.magic,
                "time": datetime.fromtimestamp(pos.time),
            })
        return result

    def get_position_summary(self) -> Dict:
        """Résumé des positions pour le dashboard."""
        positions = self.get_open_positions()
        if not positions:
            return {"count": 0, "total_pnl": 0, "total_swap": 0}

        total_pnl = sum(p["profit"] for p in positions)
        total_swap = sum(p["swap"] for p in positions)
        buy_count = sum(1 for p in positions if p["type"] == "buy")
        sell_count = sum(1 for p in positions if p["type"] == "sell")

        return {
            "count": len(positions),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_pnl": round(total_pnl, 2),
            "total_swap": round(total_swap, 2),
            "positions": positions,
        }
