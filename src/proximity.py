"""
Détection de proximité du prix actuel avec les concepts ICT.
Analyse, sur tous les timeframes, si le prix s'approche d'un OB, FVG,
OTE, zone Discount/Premium, équilibre, ou niveau de liquidité.

Utilise le PD Array range comme filtre de distance adaptatif.
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime

from .config import TIMEFRAME_LABELS
from .ict_concepts import (
    OrderBlock, FairValueGap, MarketStructureShift,
    LiquidityLevel, DiscountPremium,
)

logger = logging.getLogger("Proximity")


@dataclass
class ProximityAlert:
    """Alerte de proximité entre le prix actuel et un concept ICT."""
    concept_type: str    # "OB", "FVG", "OTE", "Discount", "Premium", "Equilibrium", "BSL", "SSL", "MSS"
    tf: str              # Timeframe du concept
    direction: str       # "bullish", "bearish", "neutral"
    level_low: float     # Niveau bas du concept
    level_high: float    # Niveau haut du concept
    price_distance: float  # Distance absolue au prix actuel
    distance_pct: float  # Distance en % du PD Array range
    strength: float      # Force du concept (0.0 - 1.0)
    detail: str = ""     # Description lisible
    is_entry_zone: bool = False  # True si le prix est DANS la zone

    def distance_label(self) -> str:
        """Label lisible de la distance."""
        if self.is_entry_zone:
            return "🎯 PRIX DANS LA ZONE"
        return f"{self.price_distance:+.1f} $"


@dataclass
class ProximitySetup:
    """
    Setup de trading dérivé des proximités ICT.
    Suggère une entrée Long/Short avec SL et TP quand
    les conditions ICT sont réunies.
    """
    direction: str        # "long" | "short"
    entry_low: float
    entry_high: float
    stop_loss: float
    target_1: float
    target_2: Optional[float] = None
    target_3: Optional[float] = None
    strength: float = 0.0
    reason: str = ""
    entry_reason: str = ""
    sl_reason: str = ""
    tp_reason: str = ""
    concepts: List[str] = field(default_factory=list)
    tfs: List[str] = field(default_factory=list)

    def risk_reward(self) -> float:
        """Ratio risque/récompense (TP1)."""
        if self.stop_loss == 0.0:
            return 0.0
        entry = (self.entry_low + self.entry_high) / 2
        if self.direction == "long":
            risk = entry - self.stop_loss
            reward = self.target_1 - entry
        else:
            risk = self.stop_loss - entry
            reward = entry - self.target_1
        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)

    @property
    def entry_mid(self) -> float:
        return (self.entry_low + self.entry_high) / 2


@dataclass
class OTEZone:
    """Optimal Trade Entry zone (50-61.8% retracement ICT)."""
    tf: str
    direction: str
    fib_50: float
    fib_618: float
    swing_high: float
    swing_low: float
    strength: float


class PriceProximityAnalyzer:
    """
    Analyse la proximité du prix actuel avec tous les concepts ICT
    sur tous les timeframes.
    """

    def __init__(self, pd_array_range: float = 50.0):
        self.pd_range = pd_array_range
        # Facteur multiplicateur du PD range pour filtrer les concepts trop loin
        self.max_distance_factor = 3.0
        # Seuil pour considérer comme "proche" (en % du PD range)
        self.close_threshold_pct = 1.0

    def analyze(
        self,
        current_price: float,
        analysis: Dict[str, dict],
    ) -> Dict[str, List[ProximityAlert]]:
        """
        Analyse complète de proximité sur tous les timeframes.
        Retourne les alertes groupées par type de concept.
        """
        if current_price <= 0 or not analysis:
            return {}

        max_dist = self.pd_range * self.max_distance_factor
        alerts: List[ProximityAlert] = []

        for tf_name, result in analysis.items():
            tf_label = TIMEFRAME_LABELS.get(tf_name, tf_name)

            # --- Order Blocks ---
            for ob in result.get("order_blocks", []):
                alert = self._check_ob(current_price, ob, tf_name, max_dist)
                if alert:
                    alerts.append(alert)

            # --- Fair Value Gaps ---
            for fvg in result.get("fvgs", []):
                alerts.extend(self._check_fvg(current_price, fvg, tf_name, max_dist))

            # --- Discount / Premium / Equilibrium ---
            dp = result.get("discount_premium")
            if dp:
                alerts.extend(self._check_dp_zones(current_price, dp, tf_name, max_dist))

            # --- OTE (Optimal Trade Entry) ---
            ote = self._compute_ote(result, tf_name, tf_label)
            if ote:
                alerts.extend(self._check_ote(current_price, ote, max_dist))

            # --- BSL / SSL Liquidity ---
            for liq in result.get("liquidity", []):
                alert = self._check_liquidity(current_price, liq, tf_name, max_dist)
                if alert:
                    alerts.append(alert)

            # --- MSS / BOS break levels ---
            for mss in result.get("mss", []):
                alert = self._check_mss(current_price, mss, tf_name, max_dist)
                if alert:
                    alerts.append(alert)

        # Trier par distance croissante (le plus proche d'abord)
        alerts.sort(key=lambda a: abs(a.price_distance) if not a.is_entry_zone else 0)

        # Grouper par type
        grouped = {
            "OB": [],
            "FVG": [],
            "OTE": [],
            "Discount": [],
            "Premium": [],
            "Equilibrium": [],
            "BSL": [],
            "SSL": [],
            "MSS": [],
        }
        for a in alerts:
            if a.concept_type in grouped:
                if len(grouped[a.concept_type]) < 3:  # max 3 par type
                    grouped[a.concept_type].append(a)

        # Nettoyer les listes vides
        return {k: v for k, v in grouped.items() if v}

    def _dist_pct(self, distance: float) -> float:
        """Distance en % du PD Array range."""
        if self.pd_range > 0:
            return abs(distance) / self.pd_range * 100
        return 0.0

    def _check_ob(
        self, price: float, ob: OrderBlock, tf: str, max_dist: float
    ) -> Optional[ProximityAlert]:
        """Vérifie la proximité d'un Order Block."""
        ob_mid = (ob.high + ob.low) / 2
        dist = price - ob_mid
        abs_dist = abs(dist)
        
        if abs_dist > max_dist * 2:
            return None

        inside = ob.low <= price <= ob.high
        entry_zone = inside
        
        # Distance: si dans l'OB, 0 = dedans; sinon distance à la zone
        if inside:
            d = 0.0
        else:
            d = dist  # positif = prix au-dessus, négatif = prix en dessous

        return ProximityAlert(
            concept_type="OB",
            tf=tf,
            direction=ob.type,
            level_low=ob.low,
            level_high=ob.high,
            price_distance=d,
            distance_pct=self._dist_pct(abs_dist),
            strength=ob.strength,
            detail=f"OB {ob.type.upper()} {TIMEFRAME_LABELS.get(tf, tf)} [{ob.low:.1f}-{ob.high:.1f}] force:{ob.strength:.0%}",
            is_entry_zone=entry_zone,
        )

    def _check_fvg(
        self, price: float, fvg: FairValueGap, tf: str, max_dist: float
    ) -> List[ProximityAlert]:
        """Vérifie la proximité d'un FVG."""
        results = []
        gap_mid = (fvg.upper + fvg.lower) / 2
        dist = price - gap_mid
        abs_dist = abs(dist)

        if abs_dist > max_dist * 2:
            return results

        inside = fvg.lower <= price <= fvg.upper

        results.append(ProximityAlert(
            concept_type="FVG",
            tf=tf,
            direction=fvg.type,
            level_low=fvg.lower,
            level_high=fvg.upper,
            price_distance=0.0 if inside else dist,
            distance_pct=self._dist_pct(abs_dist),
            strength=fvg.strength,
            detail=f"FVG {fvg.type.upper()} {TIMEFRAME_LABELS.get(tf, tf)} [{fvg.lower:.1f}-{fvg.upper:.1f}] gap:{fvg.gap_distance:.1f}",
            is_entry_zone=inside,
        ))

        return results

    def _compute_ote(self, tf_result: dict, tf_name: str, tf_label: str) -> Optional[OTEZone]:
        """Calcule la zone OTE (50-61.8% retracement) si possible."""
        dp = tf_result.get("discount_premium")
        if not dp:
            return None

        range_h = dp.range_high
        range_l = dp.range_low
        range_total = range_h - range_l
        if range_total <= 0:
            return None

        fib_50 = range_l + range_total * 0.5
        fib_618 = range_l + range_total * 0.618

        return OTEZone(
            tf=tf_name,
            direction="bullish",  # OTE est bullish dans la zone discount
            fib_50=fib_50,
            fib_618=fib_618,
            swing_high=range_h,
            swing_low=range_l,
            strength=0.7 if range_total > 0 else 0.0,
        )

    def _check_ote(
        self, price: float, ote: OTEZone, max_dist: float
    ) -> List[ProximityAlert]:
        """Vérifie la proximité de la zone OTE."""
        results = []
        ote_mid = (ote.fib_50 + ote.fib_618) / 2
        dist = price - ote_mid
        abs_dist = abs(dist)

        if abs_dist > max_dist * 2:
            return results

        inside = ote.fib_50 <= price <= ote.fib_618

        results.append(ProximityAlert(
            concept_type="OTE",
            tf=ote.tf,
            direction="bullish",
            level_low=ote.fib_50,
            level_high=ote.fib_618,
            price_distance=0.0 if inside else dist,
            distance_pct=self._dist_pct(abs_dist),
            strength=ote.strength,
            detail=f"OTE {ote.tf} zone {ote.fib_50:.1f}-{ote.fib_618:.1f} (Fib 50-61.8% du range {ote.swing_low:.1f}-{ote.swing_high:.1f})",
            is_entry_zone=inside,
        ))
        return results

    def _check_dp_zones(
        self, price: float, dp: DiscountPremium, tf: str, max_dist: float
    ) -> List[ProximityAlert]:
        """Vérifie la proximité des zones Discount/Premium/Equilibrium."""
        results = []

        # --- Discount zone ---
        discount_mid = (dp.discount_low + dp.discount_high) / 2
        dd = price - discount_mid
        if abs(dd) <= max_dist:
            inside_disc = dp.discount_low <= price <= dp.discount_high
            results.append(ProximityAlert(
                concept_type="Discount",
                tf=tf,
                direction="bullish",
                level_low=dp.discount_low,
                level_high=dp.discount_high,
                price_distance=0.0 if inside_disc else dd,
                distance_pct=self._dist_pct(abs(dd)),
                strength=0.8,
                detail=f"Zone Discount {tf} [{dp.discount_low:.1f}-{dp.discount_high:.1f}]",
                is_entry_zone=inside_disc,
            ))

        # --- Premium zone ---
        premium_mid = (dp.premium_low + dp.premium_high) / 2
        pd = price - premium_mid
        if abs(pd) <= max_dist:
            inside_prem = dp.premium_low <= price <= dp.premium_high
            results.append(ProximityAlert(
                concept_type="Premium",
                tf=tf,
                direction="bearish",
                level_low=dp.premium_low,
                level_high=dp.premium_high,
                price_distance=0.0 if inside_prem else pd,
                distance_pct=self._dist_pct(abs(pd)),
                strength=0.8,
                detail=f"Zone Premium {tf} [{dp.premium_low:.1f}-{dp.premium_high:.1f}]",
                is_entry_zone=inside_prem,
            ))

        # --- Equilibrium ---
        ed = price - dp.equilibrium
        if abs(ed) <= max_dist * 0.5:
            results.append(ProximityAlert(
                concept_type="Equilibrium",
                tf=tf,
                direction="neutral",
                level_low=dp.equilibrium,
                level_high=dp.equilibrium,
                price_distance=ed,
                distance_pct=self._dist_pct(abs(ed)),
                strength=0.6,
                detail=f"Équilibre {tf} à {dp.equilibrium:.1f}",
                is_entry_zone=False,
            ))

        return results

    def _check_liquidity(
        self, price: float, liq: LiquidityLevel, tf: str, max_dist: float
    ) -> Optional[ProximityAlert]:
        """Vérifie la proximité d'un niveau de liquidité."""
        dist = price - liq.level
        abs_dist = abs(dist)

        # Ne montrer que les liquidités proches
        if abs_dist > max_dist * 0.5:
            return None

        direction = "bullish" if liq.type == "SSL" else "bearish"
        liq_label = "BSL" if liq.type == "BSL" else "SSL"
        swept_str = " (sweep)" if liq.swept else ""

        return ProximityAlert(
            concept_type=liq.type,
            tf=tf,
            direction=direction,
            level_low=liq.level,
            level_high=liq.level,
            price_distance=dist,
            distance_pct=self._dist_pct(abs_dist),
            strength=liq.strength,
            detail=f"{liq_label} {tf} à {liq.level:.1f}{swept_str}",
            is_entry_zone=False,
        )

    def _check_mss(
        self, price: float, mss: MarketStructureShift, tf: str, max_dist: float
    ) -> Optional[ProximityAlert]:
        """Vérifie la proximité d'un niveau MSS/BOS."""
        dist = price - mss.break_level
        abs_dist = abs(dist)

        if abs_dist > max_dist * 0.5:
            return None

        return ProximityAlert(
            concept_type="MSS",
            tf=tf,
            direction=mss.direction,
            level_low=mss.break_level,
            level_high=mss.break_level,
            price_distance=dist,
            distance_pct=self._dist_pct(abs_dist),
            strength=mss.strength,
            detail=f"{mss.type} {mss.direction.upper()} {tf} à {mss.break_level:.1f}",
            is_entry_zone=False,
        )

    # ─── Setups de trading ────────────────────────────────────────────────

    def compute_setups(
        self,
        alerts: Dict[str, List[ProximityAlert]],
        analysis: Dict[str, dict],
        current_price: float,
    ) -> List[ProximitySetup]:
        """
        Génère des setups Long/Short avec SL et TP à partir des proximités.
        
        Logique ICT :
        - LONG : prix dans Discount ou OTE ou OB/FVG haussier → SL sous la zone, TP vers Premium
        - SHORT : prix dans Premium ou OB/FVG baissier → SL au-dessus, TP vers Discount
        """
        if not alerts or not analysis or current_price <= 0:
            return []

        setups: List[ProximitySetup] = []

        # Collecter le bias par TF pour confirmer la direction
        bias_long_tfs = 0
        bias_short_tfs = 0
        for tf_name in ["MN1", "W1", "D1", "H4", "H1"]:
            tf_result = analysis.get(tf_name, {})
            obs = tf_result.get("order_blocks", [])
            fvgs = tf_result.get("fvgs", [])
            for ob in obs:
                if ob.type == "bullish":
                    bias_long_tfs += 1
                elif ob.type == "bearish":
                    bias_short_tfs += 1
            for fvg in fvgs:
                if fvg.type == "bullish":
                    bias_long_tfs += 1
                elif fvg.type == "bearish":
                    bias_short_tfs += 1

        # --- SETUP LONG ---
        setup_long = self._build_long_setup(alerts, analysis, current_price, bias_long_tfs, bias_short_tfs)
        if setup_long:
            setups.append(setup_long)

        # --- SETUP SHORT ---
        setup_short = self._build_short_setup(alerts, analysis, current_price, bias_long_tfs, bias_short_tfs)
        if setup_short:
            setups.append(setup_short)

        setups.sort(key=lambda s: s.strength, reverse=True)
        return setups

    def _build_long_setup(
        self, alerts: Dict[str, List[ProximityAlert]],
        analysis: Dict[str, dict],
        price: float,
        bias_long: int,
        bias_short: int,
    ) -> Optional[ProximitySetup]:
        """Construit un setup LONG si les conditions sont réunies."""
        # Conditions pour LONG :
        # 1. Prix dans Discount zone OU OTE OU proche d'un OB haussier OU SSL
        # 2. Un SL peut être placé en dessous
        # 3. Un TP peut être placé au-dessus

        has_discount = "Discount" in alerts and any(a.is_entry_zone for a in alerts["Discount"])
        has_ote = "OTE" in alerts and any(a.is_entry_zone for a in alerts["OTE"])
        has_bullish_ob = "OB" in alerts and any(
            a.is_entry_zone and a.direction == "bullish" for a in alerts["OB"]
        )
        has_bullish_fvg = "FVG" in alerts and any(
            a.is_entry_zone and a.direction == "bullish" for a in alerts["FVG"]
        )
        has_ssl_near = "SSL" in alerts and any(
            not a.is_entry_zone and abs(a.price_distance) < self.pd_range * 0.5
            for a in alerts["SSL"]
        )

        # Au moins une condition haussière remplie
        if not (has_discount or has_ote or has_bullish_ob or has_bullish_fvg or has_ssl_near):
            return None

        # Collecter les niveaux pour le calcul SL/TP
        # IMPORTANT: seuls les supports PROCHES du prix (dans 2*PD range) sont retenus
        max_support_dist = self.pd_range * 2.0
        support_levels = []  # Niveaux sous le prix (pour SL)
        support_details = []  # Détails des supports retenus
        concepts_used = []
        tfs_used = set()
        strength_sum = 0.0
        count = 0

        for ctype in ["OB", "FVG", "Discount", "OTE", "SSL"]:
            if ctype not in alerts:
                continue
            for a in alerts[ctype]:
                # Concepts haussiers ou en zone
                if a.direction in ("bullish", "neutral") or a.is_entry_zone:
                    near_dist = abs(a.price_distance) if not a.is_entry_zone else abs(price - a.level_low)
                    if near_dist < max_support_dist or a.is_entry_zone:
                        support_levels.append(a.level_low)
                        if a.level_high > a.level_low:
                            support_levels.append(a.level_high)
                        support_details.append(f"{ctype} {a.tf} ({a.level_low:.1f}-{a.level_high:.1f})")
                    concepts_used.append(ctype)
                    tfs_used.add(a.tf)
                    count += 1
                    strength_sum += a.strength * (2.0 if a.is_entry_zone else 1.0)

        # Chercher des résistances (bearish OB/FVG) dans l'analyse complète
        res_high = 0.0
        res_detail = ""
        for tf_name, result in analysis.items():
            for ob in result.get("order_blocks", []):
                if ob.type == "bearish" and ob.low > price:
                    if res_high == 0 or ob.low < res_high:
                        res_high = ob.low
                        res_detail = f"OB baissier {TIMEFRAME_LABELS.get(tf_name, tf_name)} ({ob.low:.1f})"
            for fvg in result.get("fvgs", []):
                if fvg.type == "bearish" and fvg.lower > price:
                    if res_high == 0 or fvg.lower < res_high:
                        res_high = fvg.lower
                        res_detail = f"FVG baissier {TIMEFRAME_LABELS.get(tf_name, tf_name)} ({fvg.lower:.1f})"

        if count == 0 or not support_levels:
            return None

        # Calcul SL : sous le support le plus proche du prix
        support_levels.sort()
        nearest_support = [s for s in support_levels if s < price]
        if nearest_support:
            sl_base = max(nearest_support)
        else:
            sl_base = min(support_levels)
        sl_price = sl_base - self.pd_range * 0.15

        # Raison SL
        sl_buffer = self.pd_range * 0.15
        sl_reason_parts = []
        for d in support_details:
            if str(sl_base) in d or f"{sl_base:.1f}" in d:
                sl_reason_parts.append(d)
        if sl_reason_parts:
            sl_reason = f"SL sous {sl_reason_parts[0]} (support + buffer {sl_buffer:.1f}$)"
        else:
            sl_reason = f"SL à {sl_price:.1f}$ sous le support le plus proche ({sl_base:.1f}) + buffer {sl_buffer:.1f}$"

        # Calcul TP : vers la résistance la plus proche, ou Fibonacci 1.272
        use_fib = True
        if res_high > 0 and res_high - price > self.pd_range * 0.3:
            tp1 = res_high
            tp2 = price + self.pd_range * 1.272
            tp3 = price + self.pd_range * 1.618
            use_fib = False
        else:
            tp1 = price + self.pd_range * 1.272
            tp2 = price + self.pd_range * 1.618
            tp3 = None

        # Raison TP
        if use_fib:
            fib_range = self.pd_range
            tp_reason = f"Extension Fibonacci 1.272× PD range ({fib_range:.1f}$) → {tp1:.1f}$"
        else:
            tp_reason = f"Prochaine résistance : {res_detail}"

        # Zone d'entrée : +/- 5% du PD range
        entry_low = price - self.pd_range * 0.05
        entry_high = price + self.pd_range * 0.05

        # Raison entrée
        entry_parts = []
        if has_ote:
            entry_parts.append("zone OTE")
        if has_discount:
            entry_parts.append("zone Discount")
        if has_bullish_ob:
            entry_parts.append("OB haussier")
        if has_bullish_fvg:
            entry_parts.append("FVG haussier")
        if has_ssl_near:
            entry_parts.append("proximité SSL")
        htf_str = "favorable" if bias_long > bias_short else "neutre"
        entry_reason = f"Prix dans {' + '.join(entry_parts)} — Bias HTF {htf_str}"

        # Force du setup
        avg_strength = strength_sum / count if count > 0 else 0.0
        has_htf_bias = bias_long > bias_short
        strength = min(avg_strength * 0.5 + (0.3 if has_discount or has_ote else 0.0) + (0.2 if has_htf_bias else 0.0), 1.0)

        reason_parts = entry_parts.copy()

        return ProximitySetup(
            direction="long",
            entry_low=round(entry_low, 1),
            entry_high=round(entry_high, 1),
            stop_loss=round(sl_price, 1),
            target_1=round(tp1, 1),
            target_2=round(tp2, 1) if tp2 else None,
            target_3=round(tp3, 1) if tp3 else None,
            strength=round(strength, 2),
            reason=f"Entrée LONG possible — {" + ".join(reason_parts)} — Bias HTF {'favorable' if has_htf_bias else 'neutre'}",
            entry_reason=entry_reason,
            sl_reason=sl_reason,
            tp_reason=tp_reason,
            concepts=concepts_used,
            tfs=list(tfs_used),
        )

    def _build_short_setup(
        self, alerts: Dict[str, List[ProximityAlert]],
        analysis: Dict[str, dict],
        price: float,
        bias_long: int,
        bias_short: int,
    ) -> Optional[ProximitySetup]:
        """Construit un setup SHORT si les conditions sont réunies."""
        has_premium = "Premium" in alerts and any(a.is_entry_zone for a in alerts["Premium"])
        has_bearish_ob = "OB" in alerts and any(
            a.is_entry_zone and a.direction == "bearish" for a in alerts["OB"]
        )
        has_bearish_fvg = "FVG" in alerts and any(
            a.is_entry_zone and a.direction == "bearish" for a in alerts["FVG"]
        )
        has_bsl_near = "BSL" in alerts and any(
            not a.is_entry_zone and abs(a.price_distance) < self.pd_range * 0.5
            for a in alerts["BSL"]
        )

        if not (has_premium or has_bearish_ob or has_bearish_fvg or has_bsl_near):
            return None

        resistance_levels = []
        resistance_details = []
        max_res_dist = self.pd_range * 2.0
        concepts_used = []
        tfs_used = set()
        strength_sum = 0.0
        count = 0

        for ctype in ["OB", "FVG", "Premium", "BSL"]:
            if ctype not in alerts:
                continue
            for a in alerts[ctype]:
                if a.direction in ("bearish", "neutral") or a.is_entry_zone:
                    near_dist = abs(a.price_distance) if not a.is_entry_zone else abs(a.level_high - price)
                    if near_dist < max_res_dist or a.is_entry_zone:
                        resistance_levels.append(a.level_high)
                        resistance_details.append(f"{ctype} {a.tf} ({a.level_low:.1f}-{a.level_high:.1f})")
                    concepts_used.append(ctype)
                    tfs_used.add(a.tf)
                    count += 1
                    strength_sum += a.strength * (2.0 if a.is_entry_zone else 1.0)

        # Chercher des supports (bullish OB/FVG) dans l'analyse complète
        sup_low = 0.0
        sup_detail = ""
        for tf_name, result in analysis.items():
            for ob in result.get("order_blocks", []):
                if ob.type == "bullish" and ob.high < price:
                    if sup_low == 0 or ob.high > sup_low:
                        sup_low = ob.high
                        sup_detail = f"OB haussier {TIMEFRAME_LABELS.get(tf_name, tf_name)} ({ob.high:.1f})"
            for fvg in result.get("fvgs", []):
                if fvg.type == "bullish" and fvg.upper < price:
                    if sup_low == 0 or fvg.upper > sup_low:
                        sup_low = fvg.upper
                        sup_detail = f"FVG haussier {TIMEFRAME_LABELS.get(tf_name, tf_name)} ({fvg.upper:.1f})"

        if count == 0 or not resistance_levels:
            return None

        # SL au-dessus de la résistance la plus proche du prix
        resistance_levels.sort(reverse=True)
        nearest_res = [r for r in resistance_levels if r > price]
        if nearest_res:
            sl_base = min(nearest_res)
        else:
            sl_base = max(resistance_levels)
        sl_price = sl_base + self.pd_range * 0.15

        # Raison SL
        sl_buffer = self.pd_range * 0.15
        sl_reason_parts = []
        for d in resistance_details:
            if str(sl_base) in d or f"{sl_base:.1f}" in d:
                sl_reason_parts.append(d)
        if sl_reason_parts:
            sl_reason = f"SL au-dessus de {sl_reason_parts[0]} (résistance + buffer {sl_buffer:.1f}$)"
        else:
            sl_reason = f"SL à {sl_price:.1f}$ au-dessus de la résistance la plus proche ({sl_base:.1f}) + buffer {sl_buffer:.1f}$"

        # TP vers le support le plus proche
        use_fib = True
        if sup_low > 0 and price - sup_low > self.pd_range * 0.3:
            tp1 = sup_low
            tp2 = price - self.pd_range * 1.272
            tp3 = price - self.pd_range * 1.618
            use_fib = False
        else:
            tp1 = price - self.pd_range * 1.272
            tp2 = price - self.pd_range * 1.618
            tp3 = None

        # Raison TP
        if use_fib:
            fib_range = self.pd_range
            tp_reason = f"Extension Fibonacci 1.272× PD range ({fib_range:.1f}$) → {tp1:.1f}$"
        else:
            tp_reason = f"Prochain support : {sup_detail}"

        entry_low = price - self.pd_range * 0.05
        entry_high = price + self.pd_range * 0.05

        # Raison entrée
        entry_parts = []
        if has_premium:
            entry_parts.append("zone Premium")
        if has_bearish_ob:
            entry_parts.append("OB baissier")
        if has_bearish_fvg:
            entry_parts.append("FVG baissier")
        if has_bsl_near:
            entry_parts.append("proximité BSL")
        htf_str = "favorable" if bias_short > bias_long else "neutre"
        entry_reason = f"Prix dans {' + '.join(entry_parts)} — Bias HTF {htf_str}"

        avg_strength = strength_sum / count if count > 0 else 0.0
        has_htf_bias = bias_short > bias_long
        strength = min(avg_strength * 0.5 + (0.3 if has_premium else 0.0) + (0.2 if has_htf_bias else 0.0), 1.0)

        reason_parts = entry_parts.copy()

        return ProximitySetup(
            direction="short",
            entry_low=round(entry_low, 1),
            entry_high=round(entry_high, 1),
            stop_loss=round(sl_price, 1),
            target_1=round(tp1, 1),
            target_2=round(tp2, 1) if tp2 else None,
            target_3=round(tp3, 1) if tp3 else None,
            strength=round(strength, 2),
            reason=f"Entrée SHORT possible — {" + ".join(reason_parts)} — Bias HTF {'favorable' if has_htf_bias else 'neutre'}",
            entry_reason=entry_reason,
            sl_reason=sl_reason,
            tp_reason=tp_reason,
            concepts=concepts_used,
            tfs=list(tfs_used),
        )

    # ─── Résumé formaté ────────────────────────────────────────────────────

    def get_summary(self, alerts: Dict[str, List[ProximityAlert]]) -> str:
        """Résumé formaté des alertes de proximité."""
        if not alerts:
            return "Aucune proximité ICT détectée."

        lines = ["📍 PROXIMITÉS ICT", "=" * 55]

        order = ["OTE", "OB", "FVG", "Discount", "Premium", "Equilibrium", "BSL", "SSL", "MSS"]
        icons = {
            "OB": "🧱", "FVG": "🕳️", "OTE": "🎯", "Discount": "🟢",
            "Premium": "🔴", "Equilibrium": "⚖️", "BSL": "⬆️", "SSL": "⬇️", "MSS": "💥"
        }

        for concept_type in order:
            if concept_type not in alerts:
                continue
            items = alerts[concept_type]
            icon = icons.get(concept_type, "📍")
            lines.append(f"\n  {icon} {concept_type}")
            for a in items:
                entry_tag = " ✅" if a.is_entry_zone else ""
                lines.append(
                    f"    ├─ {a.detail} | "
                    f"Distance: {a.distance_label()}{entry_tag}"
                )

        lines.append("")
        return "\n".join(lines)
