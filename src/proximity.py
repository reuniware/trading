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
