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

from .config import TIMEFRAME_LABELS, RISK
from .ict_concepts import (
    OrderBlock, FairValueGap, MarketStructureShift,
    LiquidityLevel, DiscountPremium, PriceGap, KeyLevel, SweepSignal,
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
        key_levels: Optional[List[KeyLevel]] = None,
        sweep_signals: Optional[List[SweepSignal]] = None,
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

            # --- Price Gaps ---
            for gap in result.get("price_gaps", []):
                alert = self._check_price_gap(current_price, gap, tf_name, max_dist)
                if alert:
                    alerts.append(alert)

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
            "GAP": [],
            "OTE": [],
            "Discount": [],
            "Premium": [],
            "Equilibrium": [],
            "BSL": [],
            "SSL": [],
            "MSS": [],
            "SWEEP": [],
            "PDH": [],
            "PDL": [],
            "PWH": [],
            "PWL": [],
            "PMH": [],
            "PML": [],
        }
        for a in alerts:
            if a.concept_type in grouped:
                if len(grouped[a.concept_type]) < 3:  # max 3 par type
                    grouped[a.concept_type].append(a)

        # Nettoyer les listes vides
        result = {k: v for k, v in grouped.items() if v}

        # Ajouter les key levels comme alertes de proximité
        if key_levels:
            result = self._add_key_level_alerts(result, key_levels, current_price, max_dist)

        # Ajouter les sweep signals comme alertes
        if sweep_signals:
            result = self._add_sweep_alerts(result, sweep_signals, current_price)

        return result

    def _add_key_level_alerts(
        self, grouped: Dict, key_levels: List[KeyLevel],
        current_price: float, max_dist: float,
    ) -> Dict:
        """Ajoute les key levels (PDH, PDL, etc.) aux alertes de proximité."""
        for kl in key_levels:
            dist = current_price - kl.level
            abs_dist = abs(dist)
            if abs_dist > max_dist * 3:
                continue

            inside = abs_dist < self.pd_range * 0.02
            direction = "bearish" if kl.liquidity_type == "BSL" else "bullish"
            swept_str = f" — SWEEP {'🟢' if kl.swept else ''}" if kl.swept else ""

            alert = ProximityAlert(
                concept_type=kl.level_type,
                tf=kl.source_tf,
                direction=direction,
                level_low=kl.level,
                level_high=kl.level,
                price_distance=0.0 if inside else dist,
                distance_pct=self._dist_pct(abs_dist),
                strength=kl.strength,
                detail=f"{kl.level_type} ({kl.label}) à {kl.level:.1f} — Source: {kl.source_tf}{swept_str}",
                is_entry_zone=inside,
            )

            if kl.level_type in grouped:
                if len(grouped[kl.level_type]) < 2:
                    grouped[kl.level_type].append(alert)
            else:
                grouped[kl.level_type] = [alert]

        return grouped

    def _add_sweep_alerts(
        self, grouped: Dict, sweep_signals: List[SweepSignal],
        current_price: float,
    ) -> Dict:
        """Ajoute les sweep signals comme alertes spéciales."""
        for ss in sweep_signals:
            if not ss.confirmation:
                continue
            direction = "bullish" if ss.direction == "buy" else "bearish"
            concept_type = "SWEEP"

            alert = ProximityAlert(
                concept_type=concept_type,
                tf=ss.level.source_tf,
                direction=direction,
                level_low=ss.level.level,
                level_high=ss.level.level,
                price_distance=current_price - ss.level.level,
                distance_pct=self._dist_pct(abs(current_price - ss.level.level)),
                strength=ss.strength * 1.2,
                detail=ss.detail,
                is_entry_zone=True,
            )

            if "SWEEP" not in grouped:
                grouped["SWEEP"] = []
            grouped["SWEEP"].append(alert)

        return grouped

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

    def _check_price_gap(
        self, price: float, gap: PriceGap, tf: str, max_dist: float
    ) -> Optional[ProximityAlert]:
        """Vérifie la proximité d'un gap d'ouverture."""
        level_low = min(gap.prev_close, gap.open_price)
        level_high = max(gap.prev_close, gap.open_price)
        gap_mid = (level_low + level_high) / 2
        
        dist = price - gap_mid
        abs_dist = abs(dist)

        if abs_dist > max_dist * 2:
            return None

        inside = level_low <= price <= level_high
        direction = "bullish" if gap.direction == "up" else "bearish"
        gap_type_label = {"common": "Commun", "breakaway": "Rupture", "runaway": "Continuation", "exhaustion": "Épuisement"}.get(gap.gap_type, gap.gap_type)
        filled_str = " — refermé" if gap.filled else ""

        return ProximityAlert(
            concept_type="GAP",
            tf=tf,
            direction=direction,
            level_low=round(level_low, 1),
            level_high=round(level_high, 1),
            price_distance=0.0 if inside else dist,
            distance_pct=self._dist_pct(abs_dist),
            strength=0.7,
            detail=f"Gap {'HAUSSIER' if gap.direction == 'up' else 'BAISSIER'} {tf} ({gap_type_label} — {gap.gap_size:.1f}$)"
                   f" {gap.prev_close:.1f}→{gap.open_price:.1f}{filled_str}",
            is_entry_zone=inside,
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
        key_levels: Optional[List[KeyLevel]] = None,
        sweep_signals: Optional[List[SweepSignal]] = None,
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

        # D'abord, générer les setups basés sur les sweeps de key levels (prioritaires)
        if sweep_signals:
            for ss in sweep_signals:
                if not ss.confirmation:
                    continue
                setup = self._build_sweep_setup(ss, alerts, analysis, current_price, key_levels)
                if setup:
                    setups.append(setup)

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
        setup_long = self._build_long_setup(alerts, analysis, current_price, bias_long_tfs, bias_short_tfs, key_levels)
        if setup_long:
            setups.append(setup_long)

        # --- SETUP SHORT ---
        setup_short = self._build_short_setup(alerts, analysis, current_price, bias_long_tfs, bias_short_tfs, key_levels)
        if setup_short:
            setups.append(setup_short)

        # --- SETUPS BASÉS SUR LES KEY LEVELS ---
        if key_levels:
            kl_long = self._build_keylevel_setup("long", alerts, analysis, current_price, key_levels, bias_long_tfs, bias_short_tfs)
            if kl_long:
                setups.append(kl_long)
            kl_short = self._build_keylevel_setup("short", alerts, analysis, current_price, key_levels, bias_long_tfs, bias_short_tfs)
            if kl_short:
                setups.append(kl_short)

        # R:R minimum (configurable dans RiskConfig)
        min_rr = RISK.min_r_multiple
        setups = [s for s in setups if s.risk_reward() >= min_rr]

        setups.sort(key=lambda s: s.strength, reverse=True)
        return setups

    def _build_long_setup(
        self, alerts: Dict[str, List[ProximityAlert]],
        analysis: Dict[str, dict],
        price: float,
        bias_long: int,
        bias_short: int,
        key_levels: Optional[List[KeyLevel]] = None,
    ) -> Optional[ProximitySetup]:
        """
        Construit un setup LONG selon la méthodologie ICT :
        - SL au niveau réel du support (bas de l'OB, bas du FVG, fib_50 OTE, Discount low, SSL)
        - TP au prochain niveau de liquidité haussière (BSL : PDH > PWH > PMH)
        - Pas de buffer arbitraire ni d'extension Fibonacci
        """
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

        if not (has_discount or has_ote or has_bullish_ob or has_bullish_fvg or has_ssl_near):
            return None

        # ── Déterminer le concept principal (priorité ICT) + niveaux ──
        sl_price = None
        sl_reason = ""
        entry_low = price
        entry_high = price
        concepts_used = []
        tfs_used = set()
        strength_sum = 0.0
        count = 0

        # 1) OTE (Optimal Trade Entry) — prioritaire
        if has_ote:
            best_ote = None
            for a in alerts.get("OTE", []):
                if a.is_entry_zone:
                    if best_ote is None or a.strength > best_ote.strength:
                        best_ote = a
            if best_ote:
                sl_price = best_ote.level_low - 0.5  # 1 pip sous la zone OTE
                entry_low = best_ote.level_low
                entry_high = best_ote.level_high
                sl_reason = f"SL sous zone OTE ({best_ote.level_low:.1f})"
                concepts_used.append("OTE")
                tfs_used.add(best_ote.tf)
                strength_sum += best_ote.strength * 2.0
                count += 1

        # 2) Zone Discount
        elif has_discount:
            best_disc = None
            for a in alerts.get("Discount", []):
                if a.is_entry_zone:
                    if best_disc is None or a.strength > best_disc.strength:
                        best_disc = a
            if best_disc:
                sl_price = best_disc.level_low - 0.5  # sous la zone Discount
                entry_low = best_disc.level_low
                entry_high = best_disc.level_high
                sl_reason = f"SL sous zone Discount ({best_disc.level_low:.1f})"
                concepts_used.append("Discount")
                tfs_used.add(best_disc.tf)
                strength_sum += best_disc.strength * 2.0
                count += 1

        # 3) Order Block haussier
        elif has_bullish_ob:
            best_ob = None
            for a in alerts.get("OB", []):
                if a.is_entry_zone and a.direction == "bullish":
                    if best_ob is None or a.strength > best_ob.strength:
                        best_ob = a
            if best_ob:
                sl_price = best_ob.level_low - 0.5  # sous l'OB
                entry_low = best_ob.level_low
                entry_high = best_ob.level_high
                sl_reason = f"SL sous OB haussier ({best_ob.level_low:.1f})"
                concepts_used.append("OB")
                tfs_used.add(best_ob.tf)
                strength_sum += best_ob.strength * 2.0
                count += 1

        # 4) FVG haussier
        elif has_bullish_fvg:
            best_fvg = None
            for a in alerts.get("FVG", []):
                if a.is_entry_zone and a.direction == "bullish":
                    if best_fvg is None or a.strength > best_fvg.strength:
                        best_fvg = a
            if best_fvg:
                sl_price = best_fvg.level_low - 0.5  # sous le FVG
                entry_low = best_fvg.level_low
                entry_high = best_fvg.level_high
                sl_reason = f"SL sous FVG haussier ({best_fvg.level_low:.1f})"
                concepts_used.append("FVG")
                tfs_used.add(best_fvg.tf)
                strength_sum += best_fvg.strength * 2.0
                count += 1

        # 5) SSL (sell-side liquidity attractive)
        elif has_ssl_near:
            best_ssl = None
            for a in alerts.get("SSL", []):
                if not a.is_entry_zone and abs(a.price_distance) < self.pd_range * 0.5:
                    if best_ssl is None or a.strength > best_ssl.strength:
                        best_ssl = a
            if best_ssl:
                sl_price = best_ssl.level_low - 0.5
                sl_reason = f"SL sous SSL ({best_ssl.level_low:.1f})"
                concepts_used.append("SSL")
                tfs_used.add(best_ssl.tf)
                strength_sum += best_ssl.strength
                count += 1

        if sl_price is None or count == 0:
            return None

        # ── TP : prochain niveau BSL (buy-side liquidity) ──
        tp1, tp2, tp3 = None, None, None
        tp_reason = ""
        entry_parts = []

        if key_levels:
            # BSL = PDH, PWH, PMH non sweepés au-dessus du prix
            bsl_levels = [kl for kl in key_levels
                         if kl.liquidity_type == "BSL" and not kl.swept and kl.level > price]
            bsl_levels.sort(key=lambda k: k.level - price)

            bsl_used = []
            for bsl in bsl_levels[:3]:
                bsl_used.append(f"{bsl.level_type} ({bsl.level:.1f})")
                if tp1 is None:
                    tp1 = bsl.level
                elif tp2 is None:
                    tp2 = bsl.level
                elif tp3 is None:
                    tp3 = bsl.level

            if bsl_used:
                tp_reason = " → ".join(bsl_used)

        # Fallback : bearish OB/FVG au-dessus
        if tp1 is None:
            bearish_levels = []
            for tf_name, result in analysis.items():
                for ob in result.get("order_blocks", []):
                    if ob.type == "bearish" and ob.low > price:
                        bearish_levels.append((ob.low, f"OB {TIMEFRAME_LABELS.get(tf_name, tf_name)}"))
                for fvg in result.get("fvgs", []):
                    if fvg.type == "bearish" and fvg.lower > price:
                        bearish_levels.append((fvg.lower, f"FVG {TIMEFRAME_LABELS.get(tf_name, tf_name)}"))

            bearish_levels.sort(key=lambda x: x[0] - price)
            if bearish_levels:
                tp1 = bearish_levels[0][0]
                parts = [f"{bearish_levels[0][1]} ({tp1:.1f})"]
                if len(bearish_levels) > 1:
                    tp2 = bearish_levels[1][0]
                    parts.append(f"{bearish_levels[1][1]} ({tp2:.1f})")
                if len(bearish_levels) > 2:
                    tp3 = bearish_levels[2][0]
                    parts.append(f"{bearish_levels[2][1]} ({tp3:.1f})")
                tp_reason = " → ".join(parts)

        if tp1 is None:
            return None  # Pas de TP identifiable → pas de setup

        # ── Raison d'entrée ──
        if has_ote:
            tfs_label = sorted(set(a.tf for a in alerts.get("OTE", []) if a.is_entry_zone))
            entry_parts.append(f"zone OTE ({', '.join(tfs_label)})")
        if has_discount:
            tfs_label = sorted(set(a.tf for a in alerts.get("Discount", []) if a.is_entry_zone))
            entry_parts.append(f"zone Discount ({', '.join(tfs_label)})")
        if has_bullish_ob:
            tfs_label = sorted(set(a.tf for a in alerts.get("OB", []) if a.is_entry_zone and a.direction == "bullish"))
            entry_parts.append(f"OB haussier ({', '.join(tfs_label)})")
        if has_bullish_fvg:
            tfs_label = sorted(set(a.tf for a in alerts.get("FVG", []) if a.is_entry_zone and a.direction == "bullish"))
            entry_parts.append(f"FVG haussier ({', '.join(tfs_label)})")
        if has_ssl_near:
            tfs_label = sorted(set(a.tf for a in alerts.get("SSL", []) if not a.is_entry_zone and abs(a.price_distance) < self.pd_range * 0.5))
            entry_parts.append(f"proximité SSL ({', '.join(tfs_label)})")

        htf_str = "favorable" if bias_long > bias_short else "neutre"
        entry_reason = f"Prix dans {' + '.join(entry_parts)} — Bias HTF {htf_str}"

        # Force du setup
        has_htf_bias = bias_long > bias_short
        avg_strength = strength_sum / count if count > 0 else 0.0
        strength = min(avg_strength * 0.6 + (0.2 if has_discount or has_ote else 0.0) + (0.2 if has_htf_bias else 0.0), 1.0)

        return ProximitySetup(
            direction="long",
            entry_low=round(entry_low, 1),
            entry_high=round(entry_high, 1),
            stop_loss=round(sl_price, 1),
            target_1=round(tp1, 1),
            target_2=round(tp2, 1) if tp2 else None,
            target_3=round(tp3, 1) if tp3 else None,
            strength=round(strength, 2),
            reason=f"Entrée LONG — {' + '.join(entry_parts)} → TP: {tp_reason}",
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
        key_levels: Optional[List[KeyLevel]] = None,
    ) -> Optional[ProximitySetup]:
        """
        Construit un setup SHORT selon la méthodologie ICT :
        - SL au niveau réel de la résistance (haut de l'OB, haut du FVG, Premium high, BSL)
        - TP au prochain niveau de liquidité baissière (SSL : PDL > PWL > PML)
        - Pas de buffer arbitraire ni d'extension Fibonacci
        """
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

        # ── Déterminer le concept principal (priorité ICT) + niveaux ──
        sl_price = None
        sl_reason = ""
        entry_low = price
        entry_high = price
        concepts_used = []
        tfs_used = set()
        strength_sum = 0.0
        count = 0

        # 1) Zone Premium — prioritaire
        if has_premium:
            best_prem = None
            for a in alerts.get("Premium", []):
                if a.is_entry_zone:
                    if best_prem is None or a.strength > best_prem.strength:
                        best_prem = a
            if best_prem:
                sl_price = best_prem.level_high + 0.5  # 1 pip au-dessus de la zone Premium
                entry_low = best_prem.level_low
                entry_high = best_prem.level_high
                sl_reason = f"SL au-dessus zone Premium ({best_prem.level_high:.1f})"
                concepts_used.append("Premium")
                tfs_used.add(best_prem.tf)
                strength_sum += best_prem.strength * 2.0
                count += 1

        # 2) Order Block baissier
        elif has_bearish_ob:
            best_ob = None
            for a in alerts.get("OB", []):
                if a.is_entry_zone and a.direction == "bearish":
                    if best_ob is None or a.strength > best_ob.strength:
                        best_ob = a
            if best_ob:
                sl_price = best_ob.level_high + 0.5  # au-dessus de l'OB
                entry_low = best_ob.level_low
                entry_high = best_ob.level_high
                sl_reason = f"SL au-dessus OB baissier ({best_ob.level_high:.1f})"
                concepts_used.append("OB")
                tfs_used.add(best_ob.tf)
                strength_sum += best_ob.strength * 2.0
                count += 1

        # 3) FVG baissier
        elif has_bearish_fvg:
            best_fvg = None
            for a in alerts.get("FVG", []):
                if a.is_entry_zone and a.direction == "bearish":
                    if best_fvg is None or a.strength > best_fvg.strength:
                        best_fvg = a
            if best_fvg:
                sl_price = best_fvg.level_high + 0.5  # au-dessus du FVG
                entry_low = best_fvg.level_low
                entry_high = best_fvg.level_high
                sl_reason = f"SL au-dessus FVG baissier ({best_fvg.level_high:.1f})"
                concepts_used.append("FVG")
                tfs_used.add(best_fvg.tf)
                strength_sum += best_fvg.strength * 2.0
                count += 1

        # 4) BSL (buy-side liquidity attractive)
        elif has_bsl_near:
            best_bsl = None
            for a in alerts.get("BSL", []):
                if not a.is_entry_zone and abs(a.price_distance) < self.pd_range * 0.5:
                    if best_bsl is None or a.strength > best_bsl.strength:
                        best_bsl = a
            if best_bsl:
                sl_price = best_bsl.level_low + 0.5  # Note: level_low == level_high pour un point unique
                sl_reason = f"SL au-dessus BSL ({best_bsl.level_low:.1f})"
                concepts_used.append("BSL")
                tfs_used.add(best_bsl.tf)
                strength_sum += best_bsl.strength
                count += 1

        if sl_price is None or count == 0:
            return None

        # ── TP : prochain niveau SSL (sell-side liquidity) ──
        tp1, tp2, tp3 = None, None, None
        tp_reason = ""
        entry_parts = []

        if key_levels:
            # SSL = PDL, PWL, PML non sweepés en-dessous du prix
            ssl_levels = [kl for kl in key_levels
                         if kl.liquidity_type == "SSL" and not kl.swept and kl.level < price]
            ssl_levels.sort(key=lambda k: price - k.level)

            ssl_used = []
            for ssl in ssl_levels[:3]:
                ssl_used.append(f"{ssl.level_type} ({ssl.level:.1f})")
                if tp1 is None:
                    tp1 = ssl.level
                elif tp2 is None:
                    tp2 = ssl.level
                elif tp3 is None:
                    tp3 = ssl.level

            if ssl_used:
                tp_reason = " → ".join(ssl_used)

        # Fallback : bullish OB/FVG en-dessous
        if tp1 is None:
            bullish_levels = []
            for tf_name, result in analysis.items():
                for ob in result.get("order_blocks", []):
                    if ob.type == "bullish" and ob.high < price:
                        bullish_levels.append((ob.high, f"OB {TIMEFRAME_LABELS.get(tf_name, tf_name)}"))
                for fvg in result.get("fvgs", []):
                    if fvg.type == "bullish" and fvg.upper < price:
                        bullish_levels.append((fvg.upper, f"FVG {TIMEFRAME_LABELS.get(tf_name, tf_name)}"))

            bullish_levels.sort(key=lambda x: price - x[0])
            if bullish_levels:
                tp1 = bullish_levels[0][0]
                parts = [f"{bullish_levels[0][1]} ({tp1:.1f})"]
                if len(bullish_levels) > 1:
                    tp2 = bullish_levels[1][0]
                    parts.append(f"{bullish_levels[1][1]} ({tp2:.1f})")
                if len(bullish_levels) > 2:
                    tp3 = bullish_levels[2][0]
                    parts.append(f"{bullish_levels[2][1]} ({tp3:.1f})")
                tp_reason = " → ".join(parts)

        if tp1 is None:
            return None  # Pas de TP identifiable → pas de setup

        # ── Raison d'entrée ──
        if has_premium:
            tfs_label = sorted(set(a.tf for a in alerts.get("Premium", []) if a.is_entry_zone))
            entry_parts.append(f"zone Premium ({', '.join(tfs_label)})")
        if has_bearish_ob:
            tfs_label = sorted(set(a.tf for a in alerts.get("OB", []) if a.is_entry_zone and a.direction == "bearish"))
            entry_parts.append(f"OB baissier ({', '.join(tfs_label)})")
        if has_bearish_fvg:
            tfs_label = sorted(set(a.tf for a in alerts.get("FVG", []) if a.is_entry_zone and a.direction == "bearish"))
            entry_parts.append(f"FVG baissier ({', '.join(tfs_label)})")
        if has_bsl_near:
            tfs_label = sorted(set(a.tf for a in alerts.get("BSL", []) if not a.is_entry_zone and abs(a.price_distance) < self.pd_range * 0.5))
            entry_parts.append(f"proximité BSL ({', '.join(tfs_label)})")

        htf_str = "favorable" if bias_short > bias_long else "neutre"
        entry_reason = f"Prix dans {' + '.join(entry_parts)} — Bias HTF {htf_str}"

        # Force du setup
        has_htf_bias = bias_short > bias_long
        avg_strength = strength_sum / count if count > 0 else 0.0
        strength = min(avg_strength * 0.6 + (0.2 if has_premium else 0.0) + (0.2 if has_htf_bias else 0.0), 1.0)

        return ProximitySetup(
            direction="short",
            entry_low=round(entry_low, 1),
            entry_high=round(entry_high, 1),
            stop_loss=round(sl_price, 1),
            target_1=round(tp1, 1),
            target_2=round(tp2, 1) if tp2 else None,
            target_3=round(tp3, 1) if tp3 else None,
            strength=round(strength, 2),
            reason=f"Entrée SHORT — {' + '.join(entry_parts)} → TP: {tp_reason}",
            entry_reason=entry_reason,
            sl_reason=sl_reason,
            tp_reason=tp_reason,
            concepts=concepts_used,
            tfs=list(tfs_used),
        )

    # ─── Setup basé sur un sweep de key level ──────────────────────────

    def _build_sweep_setup(
        self, ss: SweepSignal,
        alerts: Dict[str, List[ProximityAlert]],
        analysis: Dict[str, dict],
        current_price: float,
        key_levels: Optional[List[KeyLevel]] = None,
    ) -> Optional[ProximitySetup]:
        """
        Construit un setup à partir d'un sweep de key level (Judas Swing/Turtle Soup).
        ICT : SL à 1 pip sous/au-dessus du niveau sweepé, TP vers prochaine liquidité.
        """
        direction = ss.direction  # "buy" ou "sell"
        level_price = ss.level.level
        tp1, tp2, tp3 = None, None, None
        tp_reason = ""

        if direction == "buy":
            # Sweep SSL → LONG
            entry_low = level_price
            entry_high = current_price
            sl_price = level_price - 0.5

            entry_reason = f"Sweep SSL du {ss.level.level_type} ({ss.level.label}) à {level_price:.1f}$ — prix remonté → LONG"
            sl_reason = f"SL sous {ss.level.level_type} sweepé ({level_price:.1f})"
            reason = f"🔥 SWEEP {ss.level.level_type} détecté — signal LONG"

            # TP = prochains BSL au-dessus
            if key_levels:
                bsl_levels = [kl for kl in key_levels
                             if kl.liquidity_type == "BSL" and not kl.swept and kl.level > level_price]
                bsl_levels.sort(key=lambda k: k.level - level_price)
                for bsl in bsl_levels[:3]:
                    if tp1 is None:
                        tp1 = bsl.level
                    elif tp2 is None:
                        tp2 = bsl.level
                    elif tp3 is None:
                        tp3 = bsl.level
                if tp1:
                    parts = [f"{bsl_levels[0].level_type} ({bsl_levels[0].level:.1f})"]
                    if tp2: parts.append(f"{bsl_levels[1].level_type} ({bsl_levels[1].level:.1f})")
                    if tp3: parts.append(f"{bsl_levels[2].level_type} ({bsl_levels[2].level:.1f})")
                    tp_reason = " → ".join(parts)

        else:
            # Sweep BSL → SHORT
            entry_low = current_price
            entry_high = level_price
            sl_price = level_price + 0.5

            entry_reason = f"Sweep BSL du {ss.level.level_type} ({ss.level.label}) à {level_price:.1f}$ — prix redescendu → SHORT"
            sl_reason = f"SL au-dessus {ss.level.level_type} sweepé ({level_price:.1f})"
            reason = f"🔥 SWEEP {ss.level.level_type} détecté — signal SHORT"

            # TP = prochains SSL en-dessous
            if key_levels:
                ssl_levels = [kl for kl in key_levels
                             if kl.liquidity_type == "SSL" and not kl.swept and kl.level < level_price]
                ssl_levels.sort(key=lambda k: level_price - k.level)
                for ssl in ssl_levels[:3]:
                    if tp1 is None:
                        tp1 = ssl.level
                    elif tp2 is None:
                        tp2 = ssl.level
                    elif tp3 is None:
                        tp3 = ssl.level
                if tp1:
                    parts = [f"{ssl_levels[0].level_type} ({ssl_levels[0].level:.1f})"]
                    if tp2: parts.append(f"{ssl_levels[1].level_type} ({ssl_levels[1].level:.1f})")
                    if tp3: parts.append(f"{ssl_levels[2].level_type} ({ssl_levels[2].level:.1f})")
                    tp_reason = " → ".join(parts)

        if tp1 is None:
            return None  # Pas de TP identifiable → pas de setup

        return ProximitySetup(
            direction=direction,
            entry_low=round(entry_low, 1),
            entry_high=round(entry_high, 1),
            stop_loss=round(sl_price, 1),
            target_1=round(tp1, 1) if tp1 else None,
            target_2=round(tp2, 1) if tp2 else None,
            target_3=round(tp3, 1) if tp3 else None,
            strength=min(ss.strength + 0.2, 1.0),
            reason=reason,
            entry_reason=entry_reason,
            sl_reason=sl_reason,
            tp_reason=tp_reason,
            concepts=[f"SWEEP_{ss.level.level_type}"],
            tfs=[ss.level.source_tf],
        )

    # ─── Setup basé sur les key levels (proximité) ────────────────────

    def _build_keylevel_setup(
        self, direction: str,
        alerts: Dict[str, List[ProximityAlert]],
        analysis: Dict[str, dict],
        price: float,
        key_levels: List[KeyLevel],
        bias_long: int,
        bias_short: int,
    ) -> Optional[ProximitySetup]:
        """
        Construit un setup basé sur la proximité avec un key level non sweepé.
        ICT : SL 1 pip sous/au-dessus du niveau, TP vers la liquidité suivante.
        """
        if direction == "long":
            # SSL sous le prix (PDL/PWL/PML) = support attractif
            targets = [kl for kl in key_levels
                       if kl.liquidity_type == "SSL" and not kl.swept and kl.level < price]
            if not targets:
                return None

            target = max(targets, key=lambda k: k.level)  # Plus proche du prix
            if abs(price - target.level) > self.pd_range * 5:
                return None

            entry_low = price - 1.0
            entry_high = price + 1.0
            sl_price = target.level - 0.5  # 1 pip sous l'SSL

            # TP : prochain BSL au-dessus
            bsl_levels = [kl for kl in key_levels
                         if kl.liquidity_type == "BSL" and not kl.swept and kl.level > price]
            bsl_levels.sort(key=lambda k: k.level - price)
            if bsl_levels:
                tp1 = bsl_levels[0].level
                tp2 = bsl_levels[1].level if len(bsl_levels) > 1 else None
                tp3 = bsl_levels[2].level if len(bsl_levels) > 2 else None
                tp_reason = f"{bsl_levels[0].level_type} ({bsl_levels[0].level:.1f})" + (
                    f" → {bsl_levels[1].level_type} ({bsl_levels[1].level:.1f})" if tp2 else ""
                )
            else:
                return None  # Pas de liquidité haussière identifiable

            return ProximitySetup(
                direction="long",
                entry_low=round(entry_low, 1),
                entry_high=round(entry_high, 1),
                stop_loss=round(sl_price, 1),
                target_1=round(tp1, 1),
                target_2=round(tp2, 1) if tp2 else None,
                target_3=round(tp3, 1) if tp3 else None,
                strength=0.65,
                reason=f"Proximité {target.level_type} ({target.label}) à {target.level:.1f}$ — SSL attractive",
                entry_reason=f"Entrée proche du {target.level_type} ({target.level:.1f}$) — TP {tp_reason}",
                sl_reason=f"SL sous {target.level_type} ({target.level:.1f})",
                tp_reason=tp_reason,
                concepts=[target.level_type],
                tfs=[target.source_tf],
            )
        else:
            # BSL au-dessus du prix (PDH/PWH/PMH) = résistance attractive
            targets = [kl for kl in key_levels
                       if kl.liquidity_type == "BSL" and not kl.swept and kl.level > price]
            if not targets:
                return None

            target = min(targets, key=lambda k: k.level)  # Plus proche du prix
            if abs(price - target.level) > self.pd_range * 5:
                return None

            entry_low = price - 1.0
            entry_high = price + 1.0
            sl_price = target.level + 0.5  # 1 pip au-dessus du BSL

            # TP : prochain SSL en-dessous
            ssl_levels = [kl for kl in key_levels
                         if kl.liquidity_type == "SSL" and not kl.swept and kl.level < price]
            ssl_levels.sort(key=lambda k: price - k.level)
            if ssl_levels:
                tp1 = ssl_levels[0].level
                tp2 = ssl_levels[1].level if len(ssl_levels) > 1 else None
                tp3 = ssl_levels[2].level if len(ssl_levels) > 2 else None
                tp_reason = f"{ssl_levels[0].level_type} ({ssl_levels[0].level:.1f})" + (
                    f" → {ssl_levels[1].level_type} ({ssl_levels[1].level:.1f})" if tp2 else ""
                )
            else:
                return None

            return ProximitySetup(
                direction="short",
                entry_low=round(entry_low, 1),
                entry_high=round(entry_high, 1),
                stop_loss=round(sl_price, 1),
                target_1=round(tp1, 1),
                target_2=round(tp2, 1) if tp2 else None,
                target_3=round(tp3, 1) if tp3 else None,
                strength=0.65,
                reason=f"Proximité {target.level_type} ({target.label}) à {target.level:.1f}$ — BSL attractive",
                entry_reason=f"Entrée proche du {target.level_type} ({target.level:.1f}$) — TP {tp_reason}",
                sl_reason=f"SL au-dessus {target.level_type} ({target.level:.1f})",
                tp_reason=tp_reason,
                concepts=[target.level_type],
                tfs=[target.source_tf],
            )

    # ─── Résumé formaté ────────────────────────────────────────────────────

    def get_summary(self, alerts: Dict[str, List[ProximityAlert]]) -> str:
        """Résumé formaté des alertes de proximité."""
        if not alerts:
            return "Aucune proximité ICT détectée."

        lines = ["📍 PROXIMITÉS ICT", "=" * 55]

        order = ["OTE", "OB", "FVG", "GAP", "Discount", "Premium", "Equilibrium", "BSL", "SSL", "MSS", "PDH", "PDL", "PWH", "PWL", "PMH", "PML"]
        icons = {
            "OB": "🧱", "FVG": "🕳️", "GAP": "〰️", "OTE": "🎯", "Discount": "🟢",
            "Premium": "🔴", "Equilibrium": "⚖️", "BSL": "⬆️", "SSL": "⬇️", "MSS": "💥",
            "PDH": "📈", "PDL": "📉", "PWH": "📈", "PWL": "📉", "PMH": "🏔️", "PML": "🏔️",
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
