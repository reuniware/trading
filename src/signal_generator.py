"""
Générateur de signaux de trading basé sur la confluence de concepts ICT
multi-timeframes avec scoring.
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime

from .config import TIMEFRAME_HIERARCHY
from .ict_concepts import (
    MultiTimeframeAnalyzer, OrderBlock, FairValueGap,
    MarketStructureShift, LiquidityLevel, DiscountPremium, KeyLevel, SweepSignal,
)
from .sessions import SessionDetector

logger = logging.getLogger("SignalGenerator")


@dataclass
class TradeSignal:
    symbol: str
    direction: str  # "buy" | "sell"
    score: float    # 0.0 à 100.0
    timeframe: str  # Timeframe d'exécution
    entry_zone_low: float
    entry_zone_high: float
    target_1: float
    target_2: float
    target_3: Optional[float] = None
    stop_loss: float = 0.0
    risk_percent: float = 0.0
    reason: str = ""
    concepts: Dict[str, Any] = field(default_factory=dict)
    confidence: str = "low"  # low | medium | high
    timestamp: str = ""
    bias_matrix: Dict[str, str] = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)


class SignalGenerator:
    """Génère des signaux de trading basés sur la confluence ICT multi-TF."""

    def __init__(self):
        self.analyzer = MultiTimeframeAnalyzer()
        self.session_detector = SessionDetector()

    def generate_signals(
        self,
        symbol: str,
        data: Dict[str, "pd.DataFrame"],
        key_levels: Optional[List[KeyLevel]] = None,
        sweep_signals: Optional[List[SweepSignal]] = None,
    ) -> List[TradeSignal]:
        """
        Analyse toute la structure de données et génère les signaux.
        """
        if not data:
            return []

        # Analyse multi-TF
        current_price = self._get_current_price(data)
        analysis = self.analyzer.analyze_all(data, current_price=current_price)
        bias_map = self.analyzer.get_bias_matrix(analysis, current_price=current_price)
        conflicts = self.analyzer.detect_higher_timeframe_conflict(bias_map)
        sessions = self.session_detector.get_session_stats()

        # Si pas fourni, détecter les key levels et sweeps
        if key_levels is None and data:
            key_levels = self.analyzer.detect_key_levels(data)
        if sweep_signals is None and key_levels and current_price > 0:
            sweep_signals = self.analyzer.detect_sweeps_from_key_levels(
                key_levels, data, current_price
            )

        signals: List[TradeSignal] = []

        # Générer les signaux basés sur la confluence
        buy_signal = self._evaluate_direction(
            symbol, "buy", data, analysis, bias_map, conflicts,
            sessions, key_levels, sweep_signals
        )
        if buy_signal:
            signals.append(buy_signal)

        sell_signal = self._evaluate_direction(
            symbol, "sell", data, analysis, bias_map, conflicts,
            sessions, key_levels, sweep_signals
        )
        if sell_signal:
            signals.append(sell_signal)

        # Trier par score décroissant
        signals.sort(key=lambda x: x.score, reverse=True)
        return signals

    def _evaluate_direction(
        self, symbol: str, direction: str,
        data: Dict, analysis: Dict, bias_map: Dict,
        conflicts: List[str], sessions: Dict,
        key_levels: Optional[List[KeyLevel]] = None,
        sweep_signals: Optional[List[SweepSignal]] = None,
    ) -> Optional[TradeSignal]:
        """
        Evalue un signal pour une direction donnee.
        Score normalise entre 0 et 100 avec ponderation par timeframe.
        Les zones d'entree sont calculees uniquement sur les TF d'execution (H1, M15, M5).
        """
        score = 0.0
        concepts_found = {}
        entry_low, entry_high = 0.0, 0.0
        targets = []
        stop = 0.0
        reasons = []
        current_price = 0.0

        # Poids par hierarchie de TF
        htf_weight = {"MN1": 1.0, "W1": 1.0, "D1": 1.0, "H4": 1.2, "H1": 1.3, "M15": 1.5, "M5": 1.0, "M1": 0.5}

        # === 1. Bias alignment (max +50 points) ===
        if direction == "buy":
            for tf in ["MN1", "W1", "D1"]:
                if tf in bias_map:
                    if bias_map[tf] == "bullish":
                        score += 12
                    elif bias_map[tf] == "bearish":
                        score -= 6
                    else:
                        score += 3
            for tf in ["H4", "H1", "M15"]:
                if tf in bias_map:
                    if bias_map[tf] == "bullish":
                        score += 8
                    elif bias_map[tf] == "bearish":
                        score -= 3
        else:
            for tf in ["MN1", "W1", "D1"]:
                if tf in bias_map:
                    if bias_map[tf] == "bearish":
                        score += 12
                    elif bias_map[tf] == "bullish":
                        score -= 6
                    else:
                        score += 3
            for tf in ["H4", "H1", "M15"]:
                if tf in bias_map:
                    if bias_map[tf] == "bearish":
                        score += 8
                    elif bias_map[tf] == "bullish":
                        score -= 3

        # === 2. Concepts par TF (max 1 concept fort par type/TF, max +30 points) ===
        for tf_name, result in analysis.items():
            tf_results = result
            w = htf_weight.get(tf_name, 1.0)

            # Prendre le MEILLEUR OB (le plus fort) du TF
            obs = [ob for ob in tf_results.get("order_blocks", [])
                   if (direction == "buy" and ob.type == "bullish")
                   or (direction == "sell" and ob.type == "bearish")]
            if obs:
                best_ob = max(obs, key=lambda x: x.strength)
                score += best_ob.strength * 6 * w
                concepts_found[f"ob_{tf_name}"] = best_ob
                reasons.append(f"OB {'Bullish' if direction == 'buy' else 'Bearish'} {tf_name}")

            # Prendre le MEILLEUR FVG du TF
            fvgs = [f for f in tf_results.get("fvgs", [])
                    if (direction == "buy" and f.type == "bullish")
                    or (direction == "sell" and f.type == "bearish")]
            if fvgs:
                best_fvg = max(fvgs, key=lambda x: x.strength)
                score += best_fvg.strength * 4 * w
                concepts_found[f"fvg_{tf_name}"] = best_fvg
                reasons.append(f"FVG {'Bullish' if direction == 'buy' else 'Bearish'} {tf_name}")

            # Prendre le MEILLEUR MSS du TF
            mss_list = [m for m in tf_results.get("mss", [])
                        if m.direction == direction]
            if mss_list:
                best_mss = max(mss_list, key=lambda x: x.strength)
                score += best_mss.strength * 7 * w
                reasons.append(f"MSS {direction.upper()} {tf_name} ({best_mss.type})")
                concepts_found[f"mss_{tf_name}"] = best_mss

            # Liquidite sweeps
            liq_list = [l for l in tf_results.get("liquidity", [])
                        if l.swept and (
                            (direction == "buy" and l.type == "SSL") or
                            (direction == "sell" and l.type == "BSL")
                        )]
            if liq_list:
                best_liq = max(liq_list, key=lambda x: x.strength)
                score += best_liq.strength * 4 * w
                reasons.append(f"Liquidity Sweep {tf_name}")
                concepts_found[f"liq_{tf_name}"] = best_liq

        # === 3. Bonus/Malus (max +/-15 points) ===
        if sessions.get("silver_bullet_active"):
            score += 8
            reasons.append("Silver Bullet NY active")
        if sessions.get("is_killzone_active"):
            score += 4
            reasons.append("Kill Zone active")

        # === 3b. Sweep de key levels (max +15 points) ===
        if sweep_signals:
            for ss in sweep_signals:
                if ss.confirmation and ss.direction == direction:
                    score += 12
                    reasons.append(f"SWEEP {ss.level.level_type} ({ss.level.label}) confirmé")
                elif ss.confirmation:
                    # Sweep dans la direction opposée = conflit
                    score -= 5
                    reasons.append(f"SWEEP opposé {ss.level.level_type}")

        # === 3c. Confluence de liquidité BSL/SSL (max +8 points) ===
        if key_levels:
            pd_range_confluence = self._get_pd_array_range(data)
            liq_bonus = self._score_liquidity_confluence(direction, key_levels, current_price, pd_range_confluence)
            score += liq_bonus
            if liq_bonus >= 5:
                reasons.append(f"Confluence liquidité ({liq_bonus:.0f} pts)")

        if conflicts:
            score -= 10
            reasons.append(f"Conflit TF: {', '.join(conflicts[:2])}")

        # === 4. Normalisation du score entre 0 et 100 ===
        score = max(0.0, min(score, 100.0))

        # === 5. ICT pur : zone d'entree = OB/FVG, SL sous OB, TP Fibonacci ===
        current_price = self._get_current_price(data)
        pd_range = self._get_pd_array_range(data)
        
        if current_price > 0 and score >= 20:
            entry_low, entry_high = self._calculate_entry_zone(
                direction, concepts_found, current_price, pd_range
            )
            
            # Targets ICT (Fibonacci 1.272 / 1.414 / 1.618)
            sl, tp1, tp2, tp3 = self._execute_fib_targets(
                direction, entry_low, entry_high, current_price, data, concepts_found
            )
            if sl != 0:
                stop = sl
                targets = [tp1, tp2, tp3, sl]
        
        # Niveau de confiance
        confidence = "low"
        if score >= 60:
            confidence = "high"
        elif score >= 35:
            confidence = "medium"

        if score < 15:
            return None

        # Fallback: si pas de zone d'entree, utiliser le dernier prix
        if entry_low == 0 or entry_high == 0:
            if current_price > 0:
                buffer = pd_range * 0.15 if pd_range > 0 else 10.0
                entry_low = current_price - buffer
                entry_high = current_price + buffer

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            score=round(score, 1),
            timeframe=self._get_execution_tf(direction, analysis),
            entry_zone_low=round(entry_low, 1) if entry_low else 0,
            entry_zone_high=round(entry_high, 1) if entry_high else 0,
            target_1=round(targets[0], 1) if len(targets) > 0 else 0,
            target_2=round(targets[1], 1) if len(targets) > 1 else 0,
            target_3=round(targets[2], 1) if len(targets) > 2 else None,
            stop_loss=round(stop, 1) if stop else 0,
            reason=" | ".join(reasons[:5]) if reasons else "Analyse technique",
            concepts=concepts_found,
            confidence=confidence,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            bias_matrix=bias_map,
            conflicts=conflicts,
        )

    def _get_current_price(self, data: Dict) -> float:
        """Recupere le prix actuel depuis le meilleur TF disponible."""
        for tf in ["M5", "M15", "H1"]:
            if tf in data and data[tf] is not None and len(data[tf]) > 0:
                return float(data[tf]["close"].iloc[-1])
        return 0.0

    def _get_pd_array_range(self, data: Dict) -> float:
        """
        Calcule le range de la PD Array (10 dernieres bougies M15).
        Utilise comme filtre de distance pour chercher les concepts ICT
        au lieu de l'ATR (non-ICT).
        """
        for tf in ["M15", "M5", "H1"]:
            if tf in data and data[tf] is not None and len(data[tf]) >= 10:
                df = data[tf].tail(10)
                pd_range = df["high"].max() - df["low"].min()
                return float(pd_range)
        return 50.0  # Fallback safe

    def _calculate_entry_zone(
        self, direction: str, concepts: Dict, current_price: float,
        pd_array_range: float
    ) -> Tuple[float, float]:
        """
        Calcule la zone d'entree ICT pure.
        
        Pour BUY : zone = OB/FVG haussier le plus proche SOUS le prix (discount zone)
                   filtre = PD Array range (pas d'ATR)
        Pour SELL : zone = OB/FVG baissier le plus proche AU-DESSUS du prix (premium zone)
        
        La zone d'entree C'EST la zone de l'OB/FVG elle-meme, pas un buffer.
        """
        entry_low, entry_high = 0.0, 0.0
        max_distance = pd_array_range * 2.0 if pd_array_range > 0 else 100.0
        
        # Collecter tous les niveaux de concepts pres du prix
        levels = []
        
        for key, concept in concepts.items():
            if "ob_" in key and hasattr(concept, 'low') and hasattr(concept, 'high'):
                levels.append({
                    'type': 'ob',
                    'direction': 'buy' if concept.type == 'bullish' else 'sell',
                    'entry': concept.high if concept.type == 'bullish' else concept.low,
                    'low': concept.low,
                    'high': concept.high,
                    'obj': concept,
                })
            elif "fvg_" in key and hasattr(concept, 'lower') and hasattr(concept, 'upper'):
                levels.append({
                    'type': 'fvg',
                    'direction': 'buy' if concept.type == 'bullish' else 'sell',
                    'entry': concept.lower if concept.type == 'bullish' else concept.upper,
                    'low': concept.lower,
                    'high': concept.upper,
                    'obj': concept,
                })
        
        if not levels:
            return 0.0, 0.0
        
        if direction == "buy":
            # Niveaux haussiers SOUS le prix (discount zone ICT)
            below = [l for l in levels if l['direction'] == 'buy' and l['high'] < current_price
                     and (current_price - l['high']) < max_distance]
            if below:
                # Prendre le plus proche du prix
                best = max(below, key=lambda x: x['high'])
                entry_low = best['low']
                entry_high = best['high']
            else:
                # Fallback: plus proche niveau haussier
                all_buy = [l for l in levels if l['direction'] == 'buy']
                if all_buy:
                    best = min(all_buy, key=lambda x: abs(x['entry'] - current_price))
                    entry_low = best['low']
                    entry_high = best['high']
        else:
            # Niveaux baissiers AU-DESSUS du prix (premium zone ICT)
            above = [l for l in levels if l['direction'] == 'sell' and l['low'] > current_price
                     and (l['low'] - current_price) < max_distance]
            if above:
                best = min(above, key=lambda x: x['low'])
                entry_low = best['low']
                entry_high = best['high']
            else:
                all_sell = [l for l in levels if l['direction'] == 'sell']
                if all_sell:
                    best = min(all_sell, key=lambda x: abs(x['entry'] - current_price))
                    entry_low = best['low']
                    entry_high = best['high']
        
        return entry_low, entry_high

    def _execute_fib_targets(
        self, direction: str, entry_low: float, entry_high: float,
        current_price: float, data: Dict, concepts_found: Dict
    ) -> Tuple[float, float, float, float]:
        """
        Calcule SL et TP avec Fibonacci ICT (1.272 / 1.414 / 1.618).
        
        ICT pur:
        - Utilise l'OB/PD Array du TF d'execution (M15, M5) pour les targets
        - SL sous le LOW de l'OB pour LONG / au-dessus du HIGH pour SHORT
        - TP1 : 1.272 fib extension du PD Array range
        - TP2 : 1.414 fib extension
        - TP3 : 1.618 fib extension
        
        IMPORTANT: prend le concept du TF d'execution (M15/M5/H1) pour les targets,
        pas le plus fort (qui peut etre MN1/W1 et donner des ranges absurdes).
        """
        sl, tp1, tp2, tp3 = 0.0, 0.0, 0.0, 0.0
        
        # Chercher l'OB du TF d'execution (M15, M5, H1) pour les targets
        exec_tfs = ["M15", "M5", "H1"]
        ob_concept = None
        for tf in exec_tfs:
            ob_key = f"ob_{tf}"
            if ob_key in concepts_found and hasattr(concepts_found[ob_key], 'low'):
                ob_concept = concepts_found[ob_key]
                break
        
        # Si pas d'OB, chercher le FVG du TF d'execution
        fvg_concept = None
        if not ob_concept:
            for tf in exec_tfs:
                fvg_key = f"fvg_{tf}"
                if fvg_key in concepts_found and hasattr(concepts_found[fvg_key], 'lower'):
                    fvg_concept = concepts_found[fvg_key]
                    break
        
        # Utiliser le PD Array range (10 bougies M15) comme base Fibonacci
        pd_range = self._get_pd_array_range(data)
        
        if ob_concept:
            # SL base sur l'OB du TF d'execution (zone serree)
            ob_range = abs(ob_concept.high - ob_concept.low)
            small_buffer = ob_range * 0.2 if ob_range > 0 else pd_range * 0.1
            
            if direction == "buy":
                sl = ob_concept.low - small_buffer
                tp1 = current_price + pd_range * 1.272
                tp2 = current_price + pd_range * 1.414
                tp3 = current_price + pd_range * 1.618
            else:
                sl = ob_concept.high + small_buffer
                tp1 = current_price - pd_range * 1.272
                tp2 = current_price - pd_range * 1.414
                tp3 = current_price - pd_range * 1.618
        elif fvg_concept:
            # SL base sur le FVG
            fvg_range = abs(fvg_concept.upper - fvg_concept.lower)
            small_buffer = fvg_range * 0.2 if fvg_range > 0 else pd_range * 0.1
            
            if direction == "buy":
                sl = fvg_concept.lower - small_buffer
                tp1 = current_price + pd_range * 1.272
                tp2 = current_price + pd_range * 1.414
                tp3 = current_price + pd_range * 1.618
            else:
                sl = fvg_concept.upper + small_buffer
                tp1 = current_price - pd_range * 1.272
                tp2 = current_price - pd_range * 1.414
                tp3 = current_price - pd_range * 1.618
        else:
            # Fallback: PD Array range
            if pd_range > 0:
                if direction == "buy":
                    sl = current_price - pd_range * 0.5
                    tp1 = current_price + pd_range * 1.272
                    tp2 = current_price + pd_range * 1.414
                    tp3 = current_price + pd_range * 1.618
                else:
                    sl = current_price + pd_range * 0.5
                    tp1 = current_price - pd_range * 1.272
                    tp2 = current_price - pd_range * 1.414
                    tp3 = current_price - pd_range * 1.618
            else:
                return 0.0, 0.0, 0.0, 0.0
        
        return sl, tp1, tp2, tp3

    def _get_execution_tf(self, direction: str, analysis: Dict) -> str:
        """Détermine le meilleur timeframe d'exécution."""
        for tf in ["M5", "M15"]:
            if tf in analysis:
                return tf
        return "M15"

    def _score_liquidity_confluence(
        self, direction: str, key_levels: List[KeyLevel], current_price: float,
        pd_range: float = 50.0,
    ) -> float:
        """
        Score la confluence de liquidité proche.
        Plusieurs BSL proches = forte attraction haussière.
        Plusieurs SSL proches = forte attraction baissière.
        """
        if current_price <= 0 or not key_levels:
            return 0.0

        max_dist = pd_range * 3

        score = 0.0
        if direction == "buy":
            # Compter les SSL proches = attraction baissière puis rebond = signal LONG
            ssl_near = [kl for kl in key_levels
                        if kl.liquidity_type == "SSL"
                        and abs(kl.level - current_price) < max_dist]
            if len(ssl_near) >= 2:
                score += 5
            elif len(ssl_near) == 1:
                score += 2

            # BSL sweepés au-dessus = confirmation
            bsl_swept = [kl for kl in key_levels
                         if kl.liquidity_type == "BSL" and kl.swept
                         and abs(kl.level - current_price) < max_dist]
            if len(bsl_swept) >= 1:
                score += 3
        else:
            # Compter les BSL proches = attraction haussière puis rejet = signal SHORT
            bsl_near = [kl for kl in key_levels
                        if kl.liquidity_type == "BSL"
                        and abs(kl.level - current_price) < max_dist]
            if len(bsl_near) >= 2:
                score += 5
            elif len(bsl_near) == 1:
                score += 2

            # SSL sweepés en-dessous = confirmation
            ssl_swept = [kl for kl in key_levels
                         if kl.liquidity_type == "SSL" and kl.swept
                         and abs(kl.level - current_price) < max_dist]
            if len(ssl_swept) >= 1:
                score += 3

        return score

    def get_signal_summary(self, signals: List[TradeSignal]) -> str:
        """Résumé formaté pour l'affichage."""
        if not signals:
            return "Aucun signal détecté."

        lines = []
        for s in signals:
            confidence_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(s.confidence, "⚪")
            direction_icon = "🟢 LONG" if s.direction == "buy" else "🔴 SHORT"

            lines.append(
                f"{confidence_icon} {direction_icon} | Score: {s.score:.0f}/100 | "
                f"Entrée: {s.entry_zone_low:.1f}-{s.entry_zone_high:.1f} | "
                f"TP1: {s.target_1:.1f} TP2: {s.target_2:.1f} | "
                f"SL: {s.stop_loss:.1f}"
            )
            lines.append(f"   {s.reason}")

        return "\n".join(lines)
