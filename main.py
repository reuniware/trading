"""
🏦 Système de Trading ICT Multi-Timeframes — FTMO MT5
=====================================================
Point d'entrée principal avec interface CLI.

Usage:
    python main.py                    # Lance le dashboard Streamlit
    python main.py scan               # Scan les signaux ICT en console
    python main.py analyze            # Génère un rapport complet
    python main.py positions          # Affiche les positions ouvertes
    python main.py account            # Infos compte

Auteur: Codebuff AI
"""

import sys
import logging
import argparse
from datetime import datetime

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("MT5Connector").setLevel(logging.WARNING)
logging.getLogger("DataEngine").setLevel(logging.WARNING)
logging.getLogger("ICTConcepts").setLevel(logging.WARNING)

from src.mt5_connector import MT5Connector
from src.data_engine import DataEngine
from src.analyzer import ICTAnalyzer
from src.signal_generator import SignalGenerator
from src.trade_manager import TradeManager
from src.account_monitor import AccountMonitor
from src.risk_manager import RiskManager
from src.sessions import SessionDetector
from src.config import TIMEFRAME_LABELS, TIMEFRAME_HIERARCHY


CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CHF": "CHF", "CAD": "C$", "AUD": "A$"}

def money_str(value: float, currency: str = "USD") -> str:
    """Formate un montant avec la devise correcte."""
    sym = CURRENCY_SYMBOLS.get(currency.upper(), currency)
    sign = "+" if value >= 0 else ""
    if sym in ("€", "£", "¥"):
        return f"{sign}{sym}{value:,.2f}"
    elif sym == "$":
        return f"{sign}{sym}{value:,.2f}"
    else:
        return f"{sign}{value:,.2f} {sym}"

def print_banner():
    """Affiche la bannière de démarrage."""
    print("""
╔══════════════════════════════════════════════════════════╗
║  🏦  ICT TRADING SYSTEM — Multi-Timeframe Analyzer      ║
║  📡  Connecté à FTMO Global Markets (MetaTrader 5)      ║
║  🤖  XAUUSD | ICT Concepts | Kill Zones | Signals       ║
╚══════════════════════════════════════════════════════════╝
    """)


def cmd_scan(args):
    """Scan les signaux ICT en temps réel."""
    print_banner()

    analyzer = ICTAnalyzer()
    print(f"📡 Scan de {args.symbol} sur tous les timeframes...")
    print(f"⏰ {datetime.now().strftime('%H:%M:%S')}\n")

    analysis = analyzer.analyze_symbol(args.symbol)

    if "error" in analysis:
        print(f"❌ {analysis['error']}")
        return

    # Prix actuel
    price = analysis["current_price"]
    print(f"💰 {args.symbol} — Bid: {price.get('bid', 0):.2f} | Ask: {price.get('ask', 0):.2f}")
    print(f"📊 Spread: {price.get('spread', 0):.1f} pips")
    print()

    # Matrice des biases
    print("📊 MATRICE DES BIAS")
    print("-" * 50)
    for tf_name in TIMEFRAME_HIERARCHY:
        bias = analysis["bias_matrix"].get(tf_name, "neutral")
        icons = {"bullish": "🟢 HAUSSIER", "bearish": "🔴 BAISSIER", "neutral": "🟡 NEUTRE"}
        label = TIMEFRAME_LABELS.get(tf_name, tf_name)

        # Structure
        tf_data = analysis.get("timeframes", {}).get(tf_name, {})
        structure = tf_data.get("structure", "N/A") if tf_data else "N/A"

        print(f"  {label:>6} → {icons.get(bias, '⚪'):<20} {structure}")

    # Conflits
    if analysis.get("conflicts"):
        print(f"\n⚠️  CONFLITS: {' | '.join(analysis['conflicts'])}")

    print()

    # Signaux
    signals = analysis.get("signals", [])
    if signals:
        print("🚨 SIGNAUX DE TRADING")
        print("-" * 60)
        for s in signals:
            direction = "🟢 LONG" if s.direction == "buy" else "🔴 SHORT"
            conf = {"high": "✅ Haute", "medium": "⚠️ Moyenne", "low": "❌ Basse"}.get(s.confidence, "?")
            print(f"\n  {direction} | Score: {s.score:.0f}/100 | Confiance: {conf}")
            print(f"  ├─ Entrée: {s.entry_zone_low:.1f} - {s.entry_zone_high:.1f}")
            print(f"  ├─ TP1: {s.target_1:.1f} | TP2: {s.target_2:.1f}" + (f" | TP3: {s.target_3:.1f}" if s.target_3 else ""))
            print(f"  ├─ SL:   {s.stop_loss:.1f}")
            print(f"  └─ Raison: {s.reason[:100]}")
    else:
        print("🔍 Aucun signal de trading détecté")

    # Sessions actives
    print("\n🕐 SESSIONS ACTIVES")
    print("-" * 30)
    for s in analysis["sessions"].get("active_sessions", []):
        if s.active:
            print(f"  ✅ {s.label}")
    if analysis["sessions"].get("silver_bullet_active"):
        print("  🔥 Silver Bullet NY active !")

    print()


def cmd_positions(args):
    """Affiche les positions ouvertes."""
    trade_mgr = TradeManager()
    summary = trade_mgr.get_position_summary()

    print_banner()
    print("📋 POSITIONS OUVERTES\n")

    if summary["count"] == 0:
        print("Aucune position ouverte.")
        return

    print(f"Total: {summary['count']} | LONG: {summary['buy_count']} | SHORT: {summary['sell_count']}")
    print(f"P&L Total: {summary['total_pnl']:+.2f} | Swap: {summary['total_swap']:+.2f}\n")
    print("-" * 80)

    for pos in summary["positions"]:
        direction = "🟢 LONG" if pos["type"] == "buy" else "🔴 SHORT"
        print(f"  #{pos['ticket']} {direction} {pos['symbol']}")
        print(f"  ├─ Volume: {pos['volume']} lot(s)")
        print(f"  ├─ Entrée: {pos['price_open']:.2f} | Actuel: {pos['price_current']:.2f}")
        print(f"  ├─ SL: {pos['sl']} | TP: {pos['tp']}")
        print(f"  └─ P&L: {pos['profit']:+.2f} | Swap: {pos['swap']:+.2f}\n")


def cmd_account(args):
    """Affiche les infos du compte."""
    monitor = AccountMonitor()
    stats = monitor.get_account_stats()
    perf = monitor.get_performance_summary(days=30)

    print_banner()
    print("💰 INFORMATIONS DU COMPTE\n")

    if not stats:
        print("❌ Impossible de récupérer les informations du compte.")
        return

    curr = stats.currency
    print(f"  Compte:   {stats.name} ({stats.server})")
    print(f"  Devise:   {curr}")
    print(f"  Levier:   1:{stats.leverage}")
    print()
    print(f"  Balance:     {money_str(stats.balance, curr)}")
    print(f"  Equity:      {money_str(stats.equity, curr)}")
    print(f"  Margin:      {money_str(stats.margin, curr)}")
    print(f"  Free Margin: {money_str(stats.margin_free, curr)}")
    print(f"  Margin Level: {stats.margin_level:.0f}%")
    print()
    print(f"  P&L du jour: {money_str(stats.daily_pnl, curr)} ({stats.daily_pnl_pct:+.2f}%)")
    print(f"  Trades du jour: {stats.total_trades_today} (W: {stats.winning_trades_today} | L: {stats.losing_trades_today})")

    if perf["total_trades"] > 0:
        print(f"\n  Performance (30 jours):")
        print(f"    Trades: {perf['total_trades']} | Win Rate: {perf['win_rate']:.1f}%")
        print(f"    P&L: {money_str(perf['total_profit'], curr)} | PF: {perf['profit_factor']:.2f}")


def cmd_analyze(args):
    """Génère un rapport complet et le sauvegarde."""
    analyzer = ICTAnalyzer()
    filepath = analyzer.save_report(args.symbol)
    print(f"\n📄 Rapport sauvegardé: {filepath}")
    print()

    # Afficher un aperçu
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    print(content[:2000])
    print("...")


def cmd_dashboard(args):
    """Lance le dashboard Streamlit."""
    import subprocess
    import os

    print("🚀 Lancement du dashboard Streamlit...")
    print("📊 http://localhost:8501\n")

    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        os.path.join(os.path.dirname(__file__), "src", "dashboard.py"),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ])


def main():
    # Forcer UTF-8 pour la console Windows
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(
        description="ICT Trading System - Multi-Timeframe (FTMO MT5)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command", nargs="?", default="dashboard",
        choices=["dashboard", "scan", "analyze", "positions", "account"],
        help="Commande a executer",
    )
    parser.add_argument("--symbol", "-s", default="XAUUSD", help="Symbole a analyser")
    parser.add_argument("--lot", "-l", type=float, default=0.01, help="Taille de lot")

    args = parser.parse_args()

    # Connexion MT5
    mt5 = MT5Connector()
    if not mt5.initialize():
        print("[FAIL] Impossible de se connecter a MT5. Verifiez que le terminal FTMO est ouvert.")
        sys.exit(1)

    commands = {
        "dashboard": cmd_dashboard,
        "scan": cmd_scan,
        "analyze": cmd_analyze,
        "positions": cmd_positions,
        "account": cmd_account,
    }

    cmd = commands.get(args.command)
    if cmd:
        cmd(args)


if __name__ == "__main__":
    main()
