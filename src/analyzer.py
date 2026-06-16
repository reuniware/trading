"""
Analyseur ICT complet : génère des rapports d'analyse multi-timeframes
formatés, similaires à l'analyse du fichier screenshots_tradingview/analyse_ICT_XAUUSD_20260615.md.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import pandas as pd
import numpy as np

from .config import TIMEFRAME_HIERARCHY, TIMEFRAME_LABELS, TIMEFRAME_NAMES
from .data_engine import DataEngine
from .ict_concepts import MultiTimeframeAnalyzer, DiscountPremium, KeyLevel, SweepSignal
from .sessions import SessionDetector
from .account_monitor import AccountMonitor
from .signal_generator import SignalGenerator
from .proximity import PriceProximityAnalyzer, ProximitySetup
from .setup_tracker import SetupTracker

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
        self.setup_tracker = SetupTracker(storage_path="mt5-reports/setup_tracker.json")

    def analyze_symbol(
        self, symbol: str = "XAUUSD", force_refresh: bool = False,
        timeframes: Optional[List[str]] = None,
    ) -> Dict:
        """
        Analyse complète d'un symbole sur les timeframes demandés.
        Si timeframes est None, tous les timeframes sont analysés.
        """
        active_tfs = timeframes if timeframes is not None else list(TIMEFRAME_NAMES)

        # 1. Récupérer les données
        data = self.data_engine.fetch_all_timeframes(symbol, force=force_refresh, timeframes=active_tfs)
        if not data:
            return {"error": f"Impossible de récupérer les données pour {symbol}"}

        # 2. Analyser les concepts ICT
        current_price_val = 0.0
        for tf in ["M5", "M15", "H1"]:
            if tf in data and data[tf] is not None and len(data[tf]) > 0:
                current_price_val = float(data[tf]["close"].iloc[-1])
                break

        analysis = self.mtf_analyzer.analyze_all(data, current_price=current_price_val)
        bias_map = self.mtf_analyzer.get_bias_matrix(analysis, current_price=current_price_val)
        conflicts = self.mtf_analyzer.detect_higher_timeframe_conflict(bias_map)

        # 2b. Détecter les key levels (PDH, PDL, PWH, PWL, PMH, PML) et sweeps
        key_levels = self.mtf_analyzer.detect_key_levels(data)
        sweep_signals = self.mtf_analyzer.detect_sweeps_from_key_levels(
            key_levels, data, current_price_val
        )

        # 2c. Calculer le PD Array range (commun à proximity et conformité)
        pd_range = 50.0
        for tf in ["M15", "M5", "H1"]:
            if tf in data and data[tf] is not None and len(data[tf]) >= 10:
                df_pd = data[tf].tail(10)
                pd_range = float(df_pd["high"].max() - df_pd["low"].min())
                break

        # 3. Sessions et prix actuel
        session_stats = self.sessions.get_session_stats()
        latest_price = self.data_engine.get_latest_price(symbol)

        # 3b. Conformité killzone (le prix fait-il ce qui est attendu ?)
        killzone_conformity = self.sessions.check_killzone_conformity(
            data=data, sweep_signals=sweep_signals, pd_array_range=pd_range,
        )

        # 4. Générer les signaux (avec key levels + sweeps)
        signals = self.signal_gen.generate_signals(
            symbol, data,
            key_levels=key_levels,
            sweep_signals=sweep_signals,
        )

        # 5. Données par timeframe
        tf_data = {}
        for tf_name in active_tfs:
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

        # 7. Proximité ICT (prix vs concepts) — réutilise pd_range déjà calculé
        price_val = current.get("bid", 0) or current.get("ask", 0)
        prox_analyzer = PriceProximityAnalyzer(pd_array_range=pd_range)
        proximity = prox_analyzer.analyze(
            price_val, analysis,
            key_levels=key_levels,
            sweep_signals=sweep_signals,
        )
        proximity_setups = prox_analyzer.compute_setups(
            proximity, analysis, price_val,
            key_levels=key_levels,
            sweep_signals=sweep_signals,
        )

        # Enregistrer les setups dans le tracker avec contexte complet
        if price_val > 0 and (signals or proximity_setups):
            # Construire le contexte de marché
            import json
            now_dt = datetime.now()

            # Killzone active
            kz_active = ""
            for s in session_stats.get("active_sessions", []):
                if s.active:
                    kz_active = s.label
                    break

            # Macro bias et zone de prix
            macro = self.sessions.compute_macro_context(bias_map, proximity, session_stats)

            # Concepts de proximité (compter par type)
            concept_counts = {}
            for ctype, alerts in proximity.items():
                concept_counts[ctype] = len(alerts)
            concepts_json = json.dumps(concept_counts) if concept_counts else ""

            # Score de conformité killzone
            kz_conf_score = 0.0
            if killzone_conformity and hasattr(killzone_conformity, 'conformity_score'):
                kz_conf_score = killzone_conformity.conformity_score

            context = {
                "killzone_active": kz_active,
                "macro_bias": macro.get("macro_bias", ""),
                "price_zone": macro.get("price_zone", ""),
                "pd_array_range": pd_range,
                "killzone_conformity_score": kz_conf_score,
                "nb_tfs_bullish": sum(1 for b in bias_map.values() if b == "bullish"),
                "nb_tfs_bearish": sum(1 for b in bias_map.values() if b == "bearish"),
                "nb_tfs_neutral": sum(1 for b in bias_map.values() if b == "neutral"),
                "nb_tfs_total": len(bias_map),
                "day_of_week": now_dt.weekday(),
                "hour_of_day": now_dt.hour,
                "sweep_present": len(sweep_signals) > 0,
                "proximity_concepts_json": concepts_json,
            }

            self.setup_tracker.log_setups(
                signals, price_val, symbol=symbol, source="signal", context=context,
            )
            self.setup_tracker.log_setups(
                proximity_setups, price_val, symbol=symbol, source="proximity", context=context,
            )

            # Vérifier les setups existants avec les vrais High/Low OHLC
            # IMPORTANT : on utilise iloc[-2] (bougie PRÉCÉDENTE complétée) et non iloc[-1]
            # (bougie en formation) pour éviter que les wicks intrabar ne déclenchent
            # de faux SL sur des setups valides. On préfère aussi M5 à M1 car un
            # bar M5 complété a une signification plus forte qu'un bar M1 minute.
            current_high = price_val
            current_low = price_val
            for tf_check in ["M5", "M15", "M30", "M1"]:
                if tf_check in data and data[tf_check] is not None and len(data[tf_check]) > 1:
                    prev_bar = data[tf_check].iloc[-2]  # Bougie précédente complétée
                    current_high = float(prev_bar["high"])
                    current_low = float(prev_bar["low"])
                    break
            self.setup_tracker.check_all(price_val, current_high, current_low, min_age_seconds=180)

        # 8. Compte
        account_stats = self.account.get_account_stats()

        # Score prédictif basé sur l'historique similaire
        predictive = {}
        if price_val > 0 and (signals or proximity_setups):
            # Utiliser le premier signal ou setup pour la prédiction
            first_direction = "long"
            if signals:
                first_direction = "long" if signals[0].direction == "buy" else "short"
            elif proximity_setups:
                first_direction = proximity_setups[0].direction
            predictive = self.setup_tracker.get_predictive_score(context, first_direction)

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
            "proximity": proximity,
            "proximity_setups": proximity_setups,
            "active_timeframes": active_tfs,
            "key_levels": key_levels,
            "sweep_signals": sweep_signals,
            "setup_tracker_stats": self.setup_tracker.get_stats(),
            "setup_tracker_active": self.setup_tracker.get_active(),
            "killzone_conformity": killzone_conformity,
            "predictive_score": predictive,
            "top_down_summary": self._generate_top_down_summary(bias_map, tf_data, current, active_tfs),
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
        self, bias_map: Dict, tf_data: Dict, current: Dict,
        active_tfs: Optional[List[str]] = None,
    ) -> str:
        """Génère un résumé top-down formaté pour les TFs actifs."""
        tfs = active_tfs if active_tfs else TIMEFRAME_HIERARCHY
        lines = [
            "=" * 60,
            "📊 ANALYSE ICT MULTI-TIMEFRAMES TOP-DOWN",
            "=" * 60,
            "",
        ]

        for tf_name in tfs:
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

        # Partie 3: Proximité ICT
        proximity = analysis.get("proximity", {})
        if proximity:
            lines.append("## 📍 PROXIMITÉ ICT (prix vs concepts)")
            lines.append("")
            lines.append("| Concept | Timeframe | Zone | Distance | Force |")
            lines.append("|---------|-----------|------|----------|-------|")
            order = ["OTE", "OB", "FVG", "GAP", "Discount", "Premium", "Equilibrium", "BSL", "SSL", "MSS"]
            for ctype in order:
                if ctype not in proximity:
                    continue
                for a in proximity[ctype][:2]:
                    entry_str = " 🎯" if a.is_entry_zone else ""
                    dist_str = a.distance_label()
                    lines.append(f"| **{ctype}** | {TIMEFRAME_LABELS.get(a.tf, a.tf)} | "
                                 f"{a.direction.upper()} | {dist_str}{entry_str} | {a.strength:.0%} |")

            # Détails supplémentaires
            lines.append("")
            lines.append("### Détails des proximités")
            lines.append("")
            for ctype in order:
                if ctype not in proximity:
                    continue
                lines.append(f"**{ctype}:**")
                for a in proximity[ctype][:2]:
                    entry_tag = " ✅ PRIX DANS LA ZONE" if a.is_entry_zone else ""
                    lines.append(f"- {a.detail}")
                    lines.append(f"  - Distance: {a.distance_label()}{entry_tag}")
                    lines.append(f"  - Zone: {a.level_low:.1f} – {a.level_high:.1f}")
                lines.append("")

        # Setups de trading
        setups = analysis.get("proximity_setups", [])
        if setups:
            lines.append("## 🎯 SETUPS DE TRADING (Proximité ICT)")
            lines.append("")
            lines.append("| Direction | Force | R:R | Entrée | SL | TP1 | TP2 |")
            lines.append("|-----------|-------|-----|--------|----|-----|-----|")
            for s in setups:
                direction = "🟢 LONG" if s.direction == "long" else "🔴 SHORT"
                rr = s.risk_reward()
                tp2_str = f"{s.target_2:.1f}" if s.target_2 else "-"
                lines.append(
                    f"| **{direction}** | {s.strength:.0%} | {rr} | "
                    f"{s.entry_low:.1f}-{s.entry_high:.1f} | {s.stop_loss:.1f} | "
                    f"{s.target_1:.1f} | {tp2_str} |"
                )

            lines.append("")
            lines.append("### Détails")
            lines.append("")
            for s in setups:
                direction = "🟢 LONG" if s.direction == "long" else "🔴 SHORT"
                lines.append(f"**{direction}** : {s.reason}")
                tfs_str = ', '.join(s.tfs) if s.tfs else 'N/A'
                lines.append(f"- 📡 **Timeframes:** {tfs_str}")
                lines.append(f"- 🎯 **Entrée :** {s.entry_reason}")
                lines.append(f"- 🛑 **SL :** {s.sl_reason}")
                lines.append(f"- 🎯 **TP :** {s.tp_reason}")
                lines.append("")

        # Partie 3b: Key Levels (PDH, PDL, PWH, PWL, PMH, PML)
        key_levels = analysis.get("key_levels", [])
        if key_levels:
            lines.append("## 🔑 NIVEAUX CLÉS (Key Levels)")
            lines.append("")
            lines.append("| Niveau | Prix | Type Liquidité | Distance Prix | Statut |")
            lines.append("|--------|------|----------------|---------------|--------|")
            order_kl = ["PMH", "PML", "PWH", "PWL", "PDH", "PDL"]
            kl_labels = {
                "PMH": "Plus Haut Mois Préc.", "PML": "Plus Bas Mois Préc.",
                "PWH": "Plus Haut Semaine Préc.", "PWL": "Plus Bas Semaine Préc.",
                "PDH": "Plus Haut Jour Préc.", "PDL": "Plus Bas Jour Préc.",
            }
            for lt in order_kl:
                for kl in key_levels:
                    if kl.level_type == lt:
                        dist = analysis["current_price"]["bid"] - kl.level
                        liq_type = "🟢 BSL" if kl.liquidity_type == "BSL" else "🔴 SSL"
                        status = "🔥 SWEEPÉ" if kl.swept else "✅ Intact"
                        lines.append(
                            f"| **{lt}** ({kl_labels.get(lt, lt)}) | {kl.level:.1f} | {liq_type} | "
                            f"{dist:+.1f} | {status} |"
                        )
            lines.append("")

        # Partie 3c: Conformité Killzone
        killzone_conf = analysis.get("killzone_conformity")
        if killzone_conf and hasattr(killzone_conf, 'is_active') and killzone_conf.is_active:
            lines.append("## 🔫 CONFORMITÉ KILLZONE")
            lines.append("")
            lines.append(f"- **Killzone active:** {killzone_conf.killzone_label}")
            lines.append(f"- **Conformité:** {killzone_conf.conformity_label()} ({killzone_conf.conformity_score:.0%})")
            lines.append(f"- **Attendu:** {killzone_conf.expected_behavior}")
            lines.append(f"- **Observé:** {killzone_conf.actual_behavior}")
            lines.append("")
            lines.append("**Détails:**")
            for detail in killzone_conf.details:
                lines.append(f"- {detail}")
            if killzone_conf.warning:
                lines.append(f"\n⚠️ {killzone_conf.warning}")
            lines.append("")

        # Partie 3d: Sweep signals
        sweeps = analysis.get("sweep_signals", [])
        if sweeps:
            lines.append("## 🔥 SIGNAUX DE SWEEP (Judas Swing / Turtle Soup)")
            lines.append("")
            for ss in sweeps:
                direction = "🟢 LONG" if ss.direction == "buy" else "🔴 SHORT"
                lines.append(f"- **{direction}** — {ss.detail}")
            lines.append("")

        # Partie 4: Sessions
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
