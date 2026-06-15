"""
Analyseur ICT complet : génère des rapports d'analyse multi-timeframes
formatés, similaires à l'analyse du fichier screenshots_tradingview/analyse_ICT_XAUUSD_20260615.md.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import pandas as pd
import numpy as np

from .config import TIMEFRAME_HIERARCHY, TIMEFRAME_LABELS
from .data_engine import DataEngine
from .ict_concepts import MultiTimeframeAnalyzer, DiscountPremium
from .sessions import SessionDetector
from .account_monitor import AccountMonitor
from .signal_generator import SignalGenerator

logger = logging.getLogger("Analyzer")


class ICTAnalyzer:
    """
    Analyse ICT complète multi-timeframes avec génération de rapports
    structurés, reprenant toute la méthodologie ICT (Order Blocks, FVG, MSS,
    Liquidité, Kill Zones, Discount/Premium).
    """

    def __init__(self):
        self.data_engine = DataEngine()
        self.mtf_analyzer = MultiTimeframeAnalyzer()
        self.sessions = SessionDetector()
        self.account = AccountMonitor()
        self.signal_gen = SignalGenerator()

    def analyze_symbol(self, symbol: str = "XAUUSD", force_refresh: bool = False) -> Dict:
        """
        Analyse complète d'un symbole sur tous les timeframes.
        Retourne un dictionnaire structuré avec tous les résultats.
        """
        # 1. Récupérer les données
        data = self.data_engine.fetch_all_timeframes(symbol, force=force_refresh)
        if not data:
            return {"error": f"Impossible de récupérer les données pour {symbol}"}

        # 2. Analyser les concepts ICT
        analysis = self.mtf_analyzer.analyze_all(data)
        bias_map = self.mtf_analyzer.get_bias_matrix(analysis)
        conflicts = self.mtf_analyzer.detect_higher_timeframe_conflict(bias_map)

        # 3. Sessions et prix actuel
        session_stats = self.sessions.get_session_stats()
        latest_price = self.data_engine.get_latest_price(symbol)

        # 4. Générer les signaux
        signals = self.signal_gen.generate_signals(symbol, data)

        # 5. Données par timeframe
        tf_data = {}
        for tf_name in TIMEFRAME_HIERARCHY:
            if tf_name in data and data[tf_name] is not None:
                df = data[tf_name]
                tf_data[tf_name] = self._analyze_timeframe(df, tf_name, analysis.get(tf_name, {}))

        # 6. Prix actuels
        current = {
            "bid": latest_price.get("bid", 0) if latest_price else 0,
            "ask": latest_price.get("ask", 0) if latest_price else 0,
            "spread": latest_price.get("spread", 0) if latest_price else 0,
            "time": latest_price.get("time", datetime.now()) if latest_price else datetime.now(),
        }

        # 7. Compte
        account_stats = self.account.get_account_stats()

        return {
            "symbol": symbol,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "current_price": current,
            "account": account_stats,
            "timeframes": tf_data,
            "bias_matrix": bias_map,
            "conflicts": conflicts,
            "signals": signals,
            "sessions": session_stats,
            "top_down_summary": self._generate_top_down_summary(bias_map, tf_data, current),
        }

    def _analyze_timeframe(self, df: pd.DataFrame, tf_name: str, analysis: dict) -> Dict:
        """Analyse un timeframe spécifique et calcule les métriques."""
        latest = df.iloc[-1] if len(df) > 0 else None
        if latest is None:
            return {}

        # Calcul ATR
        atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1] if len(df) > 14 else 0

        # Calcul range
        range_val = df["high"].max() - df["low"].min() if len(df) > 0 else 0

        # Volume
        avg_volume = df["volume"].mean() if len(df) > 0 else 0
        current_volume = latest.get("volume", 0)

        # Structure de marché (HH/HL, LH/LL)
        structure = self._get_market_structure(df)

        return {
            "tf_label": TIMEFRAME_LABELS.get(tf_name, tf_name),
            "current": {
                "open": latest["open"],
                "high": latest["high"],
                "low": latest["low"],
                "close": latest["close"],
                "volume": current_volume,
            },
            "atr": round(atr, 2),
            "range": round(range_val, 2),
            "avg_volume": round(avg_volume, 0),
            "structure": structure,
            "order_blocks": analysis.get("order_blocks", []),
            "fvgs": analysis.get("fvgs", []),
            "mss": analysis.get("mss", []),
            "liquidity": analysis.get("liquidity", []),
            "discount_premium": analysis.get("discount_premium"),
        }

    def _get_market_structure(self, df: pd.DataFrame) -> str:
        """Détermine la structure de marché (HH/HL, LH/LL)."""
        if len(df) < 10:
            return "N/A"

        recent = df.tail(10)
        highs = recent["high"].values
        lows = recent["low"].values

        # Détection HH/HL (haussier) vs LH/LL (baissier)
        if len(highs) >= 3:
            if highs[-1] > highs[-3] and lows[-1] > lows[-3]:
                return "HH/HL (Haussière)"
            elif highs[-1] < highs[-3] and lows[-1] < lows[-3]:
                return "LH/LL (Baissière)"
        return "Range / Consolidation"

    def _generate_top_down_summary(
        self, bias_map: Dict, tf_data: Dict, current: Dict
    ) -> str:
        """Génère un résumé top-down formaté."""
        lines = [
            "=" * 60,
            "📊 ANALYSE ICT MULTI-TIMEFRAMES TOP-DOWN",
            "=" * 60,
            "",
        ]

        for tf_name in TIMEFRAME_HIERARCHY:
            if tf_name not in tf_data:
                continue

            tf = tf_data[tf_name]
            bias = bias_map.get(tf_name, "neutral")
            label = tf.get("tf_label", tf_name)

            bias_icon = {"bullish": "🟢 HAUSSIER", "bearish": "🔴 BAISSIER", "neutral": "🟡 NEUTRE"}.get(bias, "⚪")
            struct = tf.get("structure", "N/A")
            price = tf.get("current", {})

            lines.append(f"  [{label}] Bias: {bias_icon}")
            lines.append(f"         Structure: {struct}")
            if price:
                lines.append(f"         O: {price.get('open', 0):.1f} H: {price.get('high', 0):.1f} L: {price.get('low', 0):.1f} C: {price.get('close', 0):.1f}")
            lines.append("")

        # Conflits
        conflicts = [k for k in tf_data.keys() if k in TIMEFRAME_HIERARCHY]
        lines.append("⚠️ Conflits entre timeframes: ...")
        lines.append("")

        return "\n".join(lines)

    def generate_report_text(self, symbol: str = "XAUUSD") -> str:
        """
        Génère un rapport texte complet, similaire à l'analyse TradingView
        dans screenshots_tradingview/analyse_ICT_XAUUSD_20260615.md.
        """
        analysis = self.analyze_symbol(symbol, force_refresh=True)
        if "error" in analysis:
            return f"❌ {analysis['error']}"

        lines = []
        lines.append(f"# Analyse ICT Multi-Timeframes — {symbol}")
        lines.append(f"**Date :** {analysis['timestamp']}")
        lines.append(f"**Prix actuel :** Bid {analysis['current_price']['bid']:.2f} / Ask {analysis['current_price']['ask']:.2f}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Partie 1: Matrice des biases
        lines.append("## 📊 MATRICE DES BIAS ICT")
        lines.append("")
        lines.append(f"| Timeframe | Tendance | Structure |")
        lines.append(f"|-----------|----------|-----------|")

        for tf_name in TIMEFRAME_HIERARCHY:
            if tf_name not in analysis["timeframes"]:
                continue
            tf = analysis["timeframes"][tf_name]
            bias = analysis["bias_matrix"].get(tf_name, "neutral")
            bias_icon = {"bullish": "🟢 HAUSSIER", "bearish": "🔴 BAISSIER", "neutral": "🟡 NEUTRE"}.get(bias, "⚪")
            struct = tf.get("structure", "N/A")
            lines.append(f"| **{tf.get('tf_label', tf_name)}** | {bias_icon} | {struct} |")

        lines.append("")

        # Conflits
        if analysis["conflicts"]:
            lines.append("### ⚠️ Conflits de Timeframes")
            for c in analysis["conflicts"]:
                lines.append(f"- {c}")
            lines.append("")

        # Partie 2: Concepts ICT par timeframe
        lines.append("## 🔍 CONCEPTS ICT DÉTECTÉS")
        lines.append("")

        for tf_name in TIMEFRAME_HIERARCHY:
            if tf_name not in analysis["timeframes"]:
                continue
            tf = analysis["timeframes"][tf_name]

            lines.append(f"### {tf.get('tf_label', tf_name)}")
            lines.append("")

            # Order Blocks
            obs = tf.get("order_blocks", [])
            if obs:
                lines.append(f"**Order Blocks:** {len(obs)} détectés")
                for ob in obs[:3]:
                    lines.append(f"- {ob.type.upper()} OB à {ob.low:.1f}-{ob.high:.1f} (force: {ob.strength:.0%})")
                lines.append("")

            # FVGs
            fvgs = tf.get("fvgs", [])
            if fvgs:
                lines.append(f"**Fair Value Gaps:** {len(fvgs)} détectés")
                for fvg in fvgs[:3]:
                    lines.append(f"- FVG {fvg.type.upper()} [{fvg.lower:.1f}-{fvg.upper:.1f}] (gap: {fvg.gap_distance:.1f})")
                lines.append("")

            # MSS
            mss_list = tf.get("mss", [])
            if mss_list:
                lines.append(f"**Market Structure:** {len(mss_list)} signaux")
                for mss in mss_list[:2]:
                    lines.append(f"- {mss.type} {mss.direction.upper()} à {mss.break_level:.1f}")
                lines.append("")

            # Liquidité
            liq = tf.get("liquidity", [])
            if liq:
                bsl = [l for l in liq if l.type == "BSL"]
                ssl = [l for l in liq if l.type == "SSL"]
                if bsl or ssl:
                    lines.append(f"**Liquidité:** BSL: {len(bsl)} | SSL: {len(ssl)}")
                    if any(l.swept for l in liq):
                        swept = [l for l in liq if l.swept]
                        lines.append(f"  → Sweep détecté: {len(swept)} niveaux")
                lines.append("")

            # Discount/Premium
            dp = tf.get("discount_premium")
            if dp:
                lines.append(f"**Discount/Premium:**")
                lines.append(f"- Zone Discount: {dp.discount_low:.1f} - {dp.discount_high:.1f}")
                lines.append(f"- Équilibre: {dp.equilibrium:.1f}")
                lines.append(f"- Zone Premium: {dp.premium_low:.1f} - {dp.premium_high:.1f}")
                lines.append("")

        # Partie 3: Sessions
        lines.append("## 🕐 SESSIONS & KILL ZONES")
        lines.append("")
        for s in analysis["sessions"].get("active_sessions", []):
            status = "✅ Active" if s.active else "⏳ Inactive"
            lines.append(f"- **{s.label}**: {status}")
        if analysis["sessions"].get("silver_bullet_active"):
            lines.append("- 🔥 **Silver Bullet NY active !**")
        lines.append("")

        # Partie 4: Signaux
        lines.append("## 📈 SIGNAUX DE TRADING")
        lines.append("")
        if analysis["signals"]:
            for signal in analysis["signals"]:
                direction_icon = "🟢 LONG" if signal.direction == "buy" else "🔴 SHORT"
                confidence_icon = {"high": "✅ Haute", "medium": "⚠️ Moyenne", "low": "❌ Basse"}.get(signal.confidence, "N/A")
                lines.append(f"### {direction_icon} — Score: {signal.score:.0f}/100 ({confidence_icon})")
                lines.append(f"- **Timeframe exécution:** {signal.timeframe}")
                lines.append(f"- **Zone d'entrée:** {signal.entry_zone_low:.1f} - {signal.entry_zone_high:.1f}")
                lines.append(f"- **TP1:** {signal.target_1:.1f} | **TP2:** {signal.target_2:.1f}" + (f" | **TP3:** {signal.target_3:.1f}" if signal.target_3 else ""))
                lines.append(f"- **Stop Loss:** {signal.stop_loss:.1f}")
                lines.append(f"- **Raison:** {signal.reason}")
                lines.append("")
        else:
            lines.append("Aucun signal de trading pour le moment.")
            lines.append("")

        # Disclaimer
        lines.append("---")
        lines.append("⚠️ **DISCLAIMER** : Cette analyse est générée automatiquement à des fins éducatives.")
        lines.append("Elle ne constitue pas un conseil en investissement.")
        lines.append("Le trading comporte des risques financiers importants.")
        lines.append("")

        return "\n".join(lines)

    def save_report(self, symbol: str = "XAUUSD", path: Optional[str] = None) -> str:
        """Sauvegarde le rapport dans un fichier markdown."""
        report = self.generate_report_text(symbol)
        filepath = path or f"analyse_ICT_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info("📄 Rapport sauvegardé: %s", filepath)
        return filepath
