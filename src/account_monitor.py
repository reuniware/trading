"""
Monitoring du compte de trading : solde, historique, performances.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

import pandas as pd
import MetaTrader5 as mt5

from .mt5_connector import MT5Connector

logger = logging.getLogger("AccountMonitor")


@dataclass
class AccountStats:
    balance: float
    equity: float
    margin: float
    margin_free: float
    margin_level: float
    profit: float
    daily_pnl: float
    daily_pnl_pct: float
    total_trades_today: int
    winning_trades_today: int
    losing_trades_today: int
    win_rate_today: float
    leverage: int
    currency: str
    server: str
    name: str


@dataclass
class TradeHistoryItem:
    ticket: int
    symbol: str
    type: str  # "buy" | "sell"
    volume: float
    price_open: float
    price_close: float
    profit: float
    swap: float
    commission: float
    open_time: datetime
    close_time: datetime
    duration_minutes: int
    reason: str


class AccountMonitor:
    """Surveille le compte de trading et son historique."""

    def __init__(self):
        self.mt5 = MT5Connector()
        self._daily_trades_cache: List = []

    def get_account_stats(self) -> Optional[AccountStats]:
        """Statistiques complètes du compte."""
        if not self.mt5.ensure_connected():
            return None

        account = self.mt5.get_account_info()
        if not account:
            return None

        # Calcul PnL journalier
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_trades = self._get_trades_since(today_start)

        daily_pnl = sum(t.get("profit", 0) for t in today_trades)
        winning = sum(1 for t in today_trades if t.get("profit", 0) > 0)
        losing = sum(1 for t in today_trades if t.get("profit", 0) < 0)
        total = len(today_trades)

        balance = account.get("balance", 0)
        equity = account.get("equity", 0)

        # Profit total = somme des trades uniquement (pas le PnL flottant, pas les depots)
        # MT5's account_info().profit = PnL flottant (0 si aucune position ouverte)
        # Les deals de type 2 = BALANCE (depot FTMO) sont exclus
        total_profit = 0.0
        try:
            all_deals = mt5.history_deals_get(0, 2000000000)
            if all_deals and len(all_deals) > 0:
                trades = [d for d in all_deals if d.type in (0, 1)]
                if trades:
                    total_profit = round(
                        sum(float(d.profit) + float(d.swap) + float(d.commission) for d in trades),
                        2,
                    )
        except Exception as e:
            logger.warning(f"Erreur calcul profit total: {e}")

        return AccountStats(
            balance=balance,
            equity=equity,
            margin=account.get("margin", 0),
            margin_free=account.get("margin_free", 0),
            margin_level=account.get("margin_level", 0),
            profit=total_profit,
            daily_pnl=daily_pnl,
            daily_pnl_pct=(daily_pnl / balance * 100) if balance > 0 else 0,
            total_trades_today=total,
            winning_trades_today=winning,
            losing_trades_today=losing,
            win_rate_today=(winning / total * 100) if total > 0 else 0,
            leverage=account.get("leverage", 0),
            currency=account.get("currency", "USD"),
            server=account.get("server", ""),
            name=account.get("name", ""),
        )


    def _get_trades_since(self, since: datetime) -> List:
        """Récupère l'historique des trades depuis une date."""
        if not self.mt5.ensure_connected():
            return []

        history = mt5.history_deals_get(since, datetime.now())
        if not history:
            return []

        return [
            {
                "ticket": deal.ticket,
                "symbol": deal.symbol,
                "type": "buy" if deal.type == 0 else "sell",
                "volume": deal.volume,
                "price": deal.price,
                "profit": deal.profit,
                "swap": deal.swap,
                "commission": deal.commission,
                "time": datetime.fromtimestamp(deal.time),
            }
            for deal in history
        ]

    def get_trade_history(
        self, days: Optional[int] = 30, symbol: Optional[str] = None
    ) -> List[TradeHistoryItem]:
        """
        Récupère l'historique des trades.
        days=None -> TOUS les trades (utilise position range int).
        """
        if not self.mt5.ensure_connected():
            return []

        if days is None:
            # Tous les trades via position range (int) pour eviter les soucis de timezone
            history = mt5.history_deals_get(0, 2000000000)
        else:
            since = datetime.now() - timedelta(days=days)
            history = mt5.history_deals_get(since, datetime.now())
        if not history:
            return []

        items = []
        for deal in history:
            # Filtrer les deals non-trade: 0=BUY, 1=SELL seulement
            # Les types 2=BALANCE (depot FTMO), 3=CREDIT, etc. ne sont pas des trades
            if deal.type not in (0, 1):
                continue
            if symbol and deal.symbol != symbol:
                continue

            duration = (datetime.fromtimestamp(deal.time) - datetime.fromtimestamp(deal.time_msc / 1000)) if deal.time_msc > 0 else timedelta()
            minutes = int(duration.total_seconds() / 60)

            items.append(TradeHistoryItem(
                ticket=deal.ticket,
                symbol=deal.symbol,
                type="buy" if deal.type % 2 == 0 else "sell",
                volume=deal.volume,
                price_open=deal.price,
                price_close=deal.price,  # Approximation
                profit=deal.profit,
                swap=deal.swap,
                commission=deal.commission,
                open_time=datetime.fromtimestamp(deal.time_msc / 1000) if deal.time_msc > 0 else datetime.fromtimestamp(deal.time),
                close_time=datetime.fromtimestamp(deal.time),
                duration_minutes=minutes,
                reason=deal.comment or "",
            ))

        return items

    def get_performance_summary(self, days: Optional[int] = 30) -> Dict:
        """Résumé des performances."""
        trades = self.get_trade_history(days=days)

        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "total_profit": 0,
                "avg_profit": 0,
                "max_profit": 0,
                "max_loss": 0,
                "profit_factor": 0,
                "sharpe_approx": 0,
            }

        # Total PnL incluant swaps et commissions (comme MT5)
        gross_totals = [t.profit + t.swap + t.commission for t in trades]
        winning = [p for p in gross_totals if p > 0]
        losing = [p for p in gross_totals if p <= 0]
        total_profit = sum(winning)
        total_loss = abs(sum(losing))
        gross_pnl = sum(gross_totals)

        return {
            "total_trades": len(trades),
            "win_rate": round(len(winning) / len(trades) * 100, 1) if trades else 0,
            "total_profit": round(gross_pnl, 2),
            "avg_profit": round(sum(gross_totals) / len(gross_totals), 2) if gross_totals else 0,
            "max_profit": round(max(gross_totals), 2) if gross_totals else 0,
            "max_loss": round(min(gross_totals), 2) if gross_totals else 0,
            "profit_factor": round(total_profit / total_loss, 2) if total_loss > 0 else float("inf"),
            "avg_duration_min": round(sum(t.duration_minutes for t in trades) / len(trades), 1) if trades else 0,
        }

    def get_equity_curve(self, days: Optional[int] = 30) -> pd.DataFrame:
        """Courbe d'equity basée sur l'historique."""
        trades = self.get_trade_history(days=days)
        if not trades:
            return pd.DataFrame()

        trades.sort(key=lambda t: t.close_time)
        data = []
        cumulative_pnl = 0

        for t in trades:
            cumulative_pnl += t.profit
            data.append({
                "time": t.close_time,
                "pnl": cumulative_pnl,
                "trade_profit": t.profit,
            })

        return pd.DataFrame(data)
