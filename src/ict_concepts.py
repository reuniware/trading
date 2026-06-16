"""
Détection des concepts ICT : Order Blocks, Fair Value Gaps,
Market Structure Shifts, Liquidité (BSL/SSL), Discount/Premium.

Basé sur la méthodologie Inner Circle Trader (ICT).
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

from .config import ICT as ict_config

logger = logging.getLogger("ICTConcepts")


# ─── Dataclasses de résultats ───────────────────────────────────────────────

@dataclass
class OrderBlock:
    tf: str
    type: str  # "bullish" | "bearish"
    high: float
    low: float
    index: int  # Position dans le DataFrame
    time: Any    # Timestamp
    strength: float  # 0.0 à 1.0
    mitigated: bool = False

@dataclass
class FairValueGap:
    tf: str
    type: str  # "bullish" | "bearish"
    upper: float
    lower: float
    index: int
    time: Any
    strength: float
    mitigated: bool = False
    gap_distance: float = 0.0

@dataclass
class MarketStructureShift:
    tf: str
    type: str  # "MSS" (shift) | "BOS" (break)
    direction: str  # "bullish" | "bearish"
    break_level: float
    index: int
    time: Any
    strength: float

@dataclass
class LiquidityLevel:
    tf: str
    type: str  # "BSL" (buy-side) | "SSL" (sell-side)
    level: float
    index: int
    time: Any
    strength: float
    swept: bool = False

@dataclass
class PriceGap:
    """
    Gap d'ouverture : écart entre le close de la bougie précédente
    et l'open de la bougie actuelle. Types :
    - common : gap normal (< 1× ATR)
    - breakaway : gap de rupture (1-2× ATR)
    - runaway : gap de continuation (2-3× ATR)
    - exhaustion : gap d'épuisement (> 3× ATR)
    """
    tf: str
    direction: str  # "up" | "down"
    gap_size: float  # Taille absolue du gap
    open_price: float
    prev_close: float
    gap_percent: float  # % du prix
    index: int
    time: Any
    gap_type: str = "common"  # common | breakaway | runaway | exhaustion
    filled: bool = False  # True si le gap a été refermé


@dataclass
class DiscountPremium:
    """Niveaux de Discount (zone achat) et Premium (zone vente)."""
    tf: str
    equilibrium: float  # Point d'équilibre (milieu du range)
    discount_low: float
    discount_high: float
    premium_low: float
    premium_high: float
    range_high: float
    range_low: float


@dataclass
class KeyLevel:
    """
    Niveau de prix clé : PDH, PDL, PWH, PWL, PMH, PML.
    Ces niveaux sont des zones de liquidité naturelles que le prix
    cherche à atteindre (BSL au-dessus, SSL en-dessous).
    """
    level_type: str   # "PDH" | "PDL" | "PWH" | "PWL" | "PMH" | "PML"
    level: float
    time: Any          # Timestamp de la bougie source
    source_tf: str     # "D1", "W1", "MN1"
    strength: float    # 0.0 à 1.0 (PMH/PML > PWH/PWL > PDH/PDL)
    swept: bool = False
    sweep_direction: Optional[str] = None  # "up" | "down" | None

    @property
    def liquidity_type(self) -> str:
        """BSL si le niveau est un haut (PDH, PWH, PMH), SSL si bas."""
        return "BSL" if self.level_type in ("PDH", "PWH", "PMH") else "SSL"

    @property
    def label(self) -> str:
        labels = {
            "PDH": "Plus Haut du Jour Précédent",
            "PDL": "Plus Bas du Jour Précédent",
            "PWH": "Plus Haut de la Semaine Précédente",
            "PWL": "Plus Bas de la Semaine Précédente",
            "PMH": "Plus Haut du Mois Précédent",
            "PML": "Plus Bas du Mois Précédent",
        }
        return labels.get(self.level_type, self.level_type)


@dataclass
class SweepSignal:
    """
    Signal de sweep de liquidité ICT.
    Judas Swing / Turtle Soup : le prix casse un niveau clé
    puis s'inverse — signal de trading très puissant.
    """
    level: KeyLevel
    direction: str      # "buy" (sweep SSL → remonte) | "sell" (sweep BSL → redescend)
    sweep_bar_index: int
    sweep_bar_time: Any
    confirmation: bool  # True si le prix a confirmé le reversal
    strength: float
    detail: str = ""


# ─── Détecteurs ─────────────────────────────────────────────────────────────

class ICTConceptsDetector:
    """Détecte les concepts ICT sur un DataFrame OHLC."""

    def __init__(self, tf_name: str):
        self.tf = tf_name
        self.cfg = ict_config

    # ── Order Blocks ────────────────────────────────────────────────────────

    def detect_order_blocks(self, df: pd.DataFrame) -> List[OrderBlock]:
        """
        Détecte les Order Blocks ICT.
        Bullish OB: dernière bougie baissière avant une forte impulsion haussière.
        Bearish OB: dernière bougie haussière avant une forte impulsion baissière.
        """
        blocks: List[OrderBlock] = []
        if df is None or len(df) < 5:
            return blocks

        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values

        for i in range(2, len(df) - 2):
            # Bougie actuelle (impulsion)
            curr_body = abs(closes[i] - opens[i])
            prev_body = abs(closes[i-1] - opens[i-1])
            prev_range = highs[i-1] - lows[i-1]
            curr_range = highs[i] - lows[i]

            # Vérifier que la bougie précédente a un corps significatif (> 20% du range)
            prev_body_ratio = prev_body / (prev_range + 1e-8)
            if prev_body_ratio < 0.2:
                continue

            # Impulsion haussière
            if (closes[i] > opens[i] and closes[i] > closes[i-1] 
                and curr_body > prev_body * 1.5
                and closes[i-1] < opens[i-1]):  # Bougie baissière avant
                
                strength = min(curr_body / prev_body / 3.0, 1.0)
                
                blocks.append(OrderBlock(
                    tf=self.tf, type="bullish",
                    high=highs[i-1], low=lows[i-1],
                    index=i-1, time=df.index[i-1],
                    strength=round(strength, 2),
                ))

            # Impulsion baissière
            elif (closes[i] < opens[i] and closes[i] < closes[i-1]
                  and curr_body > prev_body * 1.5
                  and closes[i-1] > opens[i-1]):  # Bougie haussière avant
                
                strength = min(curr_body / prev_body / 3.0, 1.0)
                
                blocks.append(OrderBlock(
                    tf=self.tf, type="bearish",
                    high=highs[i-1], low=lows[i-1],
                    index=i-1, time=df.index[i-1],
                    strength=round(strength, 2),
                ))

        return blocks

    # ── Fair Value Gaps ─────────────────────────────────────────────────────

    def detect_fvg(self, df: pd.DataFrame) -> List[FairValueGap]:
        """
        Détecte les Fair Value Gaps (FVG) ICT.
        Bullish FVG: gap entre low[i-1] et high[i+1] (trois bougies haussières).
        Bearish FVG: gap entre high[i-1] et low[i+1] (trois bougies baissières).
        """
        gaps: List[FairValueGap] = []
        if df is None or len(df) < 5:
            return gaps

        highs = df["high"].values
        lows = df["low"].values
        opens = df["open"].values
        closes = df["close"].values

        for i in range(1, len(df) - 2):
            # === Bullish FVG: 3 bougies → gap vers le haut ===
            # Candle 0 (i-1): doit être baissière (close < open) 
            # Candle 1 (i): impulse haussière
            # Candle 2 (i+1): doit être haussière (close > open) avec low > high de candle 0
            if (closes[i-1] < opens[i-1] and closes[i] > opens[i] and closes[i+1] > opens[i+1] 
                and lows[i+1] > highs[i-1]):
                gap_dist = lows[i+1] - highs[i-1]
                strength = min(gap_dist / (highs[i-1] - lows[i-1] + 1e-8) / 2.0, 1.0)
                gaps.append(FairValueGap(
                    tf=self.tf, type="bullish",
                    upper=lows[i+1], lower=highs[i-1],
                    index=i, time=df.index[i],
                    strength=round(strength, 2),
                    gap_distance=round(gap_dist, 2),
                ))

            # === Bearish FVG: 3 bougies → gap vers le bas ===
            # Candle 0 (i-1): doit être haussière (close > open)
            # Candle 1 (i): impulse baissière
            # Candle 2 (i+1): doit être baissière (close < open) avec high < low de candle 0
            elif (closes[i-1] > opens[i-1] and closes[i] < opens[i] and closes[i+1] < opens[i+1]
                  and highs[i+1] < lows[i-1]):
                gap_dist = lows[i-1] - highs[i+1]
                strength = min(gap_dist / (highs[i-1] - lows[i-1] + 1e-8) / 2.0, 1.0)
                gaps.append(FairValueGap(
                    tf=self.tf, type="bearish",
                    upper=lows[i-1], lower=highs[i+1],
                    index=i, time=df.index[i],
                    strength=round(strength, 2),
                    gap_distance=round(gap_dist, 2),
                ))

        return gaps

    # ── Market Structure Shift (MSS/BOS) ────────────────────────────────────

    def detect_mss(self, df: pd.DataFrame) -> List[MarketStructureShift]:
        """
        Détecte les Market Structure Shifts (MSS) et Breaks of Structure (BOS).
        Bullish MSS: cassure d'un précédent swing high avec momentum.
        Bearish MSS: cassure d'un précédent swing low avec momentum.
        """
        shifts: List[MarketStructureShift] = []
        if df is None or len(df) < self.cfg.mss_lookback:
            return shifts

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        lookback = self.cfg.mss_lookback

        for i in range(lookback, len(df)):
            window_highs = highs[i-lookback:i]
            window_lows = lows[i-lookback:i]

            prev_swing_high = np.max(window_highs[:-1])
            prev_swing_low = np.min(window_lows[:-1])

            # Cassure haussière (BOS/MSS bullish)
            if closes[i] > prev_swing_high:
                break_pct = (closes[i] - prev_swing_high) / prev_swing_high * 100
                strength = min(break_pct / self.cfg.mss_min_break_percent / 5.0, 1.0)
                shift_type = "MSS" if self._is_shift_high(df, i) else "BOS"
                shifts.append(MarketStructureShift(
                    tf=self.tf, type=shift_type, direction="bullish",
                    break_level=prev_swing_high,
                    index=i, time=df.index[i],
                    strength=round(strength, 2),
                ))

            # Cassure baissière (BOS/MSS bearish)
            elif closes[i] < prev_swing_low:
                break_pct = (prev_swing_low - closes[i]) / prev_swing_low * 100
                strength = min(break_pct / self.cfg.mss_min_break_percent / 5.0, 1.0)
                shift_type = "MSS" if self._is_shift_low(df, i) else "BOS"
                shifts.append(MarketStructureShift(
                    tf=self.tf, type=shift_type, direction="bearish",
                    break_level=prev_swing_low,
                    index=i, time=df.index[i],
                    strength=round(strength, 2),
                ))

        return shifts

    def _is_shift_high(self, df: pd.DataFrame, idx: int) -> bool:
        """Vérifie si la cassure haute est un vrai MSS (HH/HL cassé)."""
        if idx < 3:
            return False
        now_low = min(df["low"].iloc[idx], df["low"].iloc[idx-1])
        prev_low = min(df["low"].iloc[idx-2], df["low"].iloc[idx-3])
        return now_low > prev_low

    def _is_shift_low(self, df: pd.DataFrame, idx: int) -> bool:
        """Vérifie si la cassure basse est un vrai MSS (LH/LL cassé)."""
        if idx < 3:
            return False
        now_high = max(df["high"].iloc[idx], df["high"].iloc[idx-1])
        prev_high = max(df["high"].iloc[idx-2], df["high"].iloc[idx-3])
        return now_high < prev_high

    # ── Liquidité (BSL/SSL) ─────────────────────────────────────────────────

    def detect_liquidity(self, df: pd.DataFrame) -> List[LiquidityLevel]:
        """
        Détecte les zones de liquidité:
        BSL (Buy-Side Liquidity): au-dessus des swing highs
        SSL (Sell-Side Liquidity): en-dessous des swing lows
        """
        levels: List[LiquidityLevel] = []
        if df is None or len(df) < 30:
            return levels

        highs = df["high"].values
        lows = df["low"].values
        lookback = min(self.cfg.liq_lookback, len(df) - 1)

        # Détection des swing points
        for i in range(5, len(df) - 5):
            # Swing High (BSL)
            if all(highs[i] > highs[i-j] for j in range(1, 4) if i-j >= 0) and \
               all(highs[i] > highs[i+j] for j in range(1, 4) if i+j < len(highs)):
                strength = min((highs[i] - np.mean(lows[max(0,i-10):i+10])) / highs[i] * 100, 1.0)
                levels.append(LiquidityLevel(
                    tf=self.tf, type="BSL",
                    level=highs[i], index=i,
                    time=df.index[i],
                    strength=round(strength, 2),
                ))

            # Swing Low (SSL)
            elif all(lows[i] < lows[i-j] for j in range(1, 4) if i-j >= 0) and \
                 all(lows[i] < lows[i+j] for j in range(1, 4) if i+j < len(lows)):
                strength = min((np.mean(highs[max(0,i-10):i+10]) - lows[i]) / lows[i] * 100, 1.0)
                levels.append(LiquidityLevel(
                    tf=self.tf, type="SSL",
                    level=lows[i], index=i,
                    time=df.index[i],
                    strength=round(strength, 2),
                ))

        return levels

    def detect_sweeps(
        self, df: pd.DataFrame, levels: List[LiquidityLevel]
    ) -> List[LiquidityLevel]:
        """Détecte les sweeps de liquidité (niveaux déjà cassés)."""
        if df is None or len(df) < 2:
            return levels

        current_high = df["high"].iloc[-1]
        current_low = df["low"].iloc[-1]
        current_close = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]

        for level in levels:
            if level.swept:
                continue
            # SSL sweep: prix va sous le niveau puis remonte
            if level.type == "SSL" and current_low <= level.level and current_close > level.level:
                level.swept = True
            # BSL sweep: prix va au-dessus du niveau puis redescend
            elif level.type == "BSL" and current_high >= level.level and current_close < level.level:
                level.swept = True

        return levels

    # ── Price Gaps (gaps d'ouverture) ─────────────────────────────────────

    def detect_price_gaps(self, df: pd.DataFrame) -> List[PriceGap]:
        """
        Détecte les gaps d'ouverture : écart entre close[i-1] et open[i].
        Types selon le contexte de marché :
        - common : gap normal (< 1× ATR)
        - breakaway : gap de rupture en sortie de range
        - runaway : gap de continuation en trend
        - exhaustion : gap d'épuisement
        """
        gaps: List[PriceGap] = []
        if df is None or len(df) < 10:
            return gaps

        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values

        # Calcul ATR approximatif (sur 14 périodes)
        atr_values = []
        for i in range(1, len(df)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            atr_values.append(tr)
        atr = float(np.mean(atr_values[-14:])) if len(atr_values) >= 14 else float(np.mean(atr_values)) if atr_values else 0
        atr = max(atr, 0.01)  # Éviter division par zéro

        # Seuil minimum : 0.3× ATR (ignorer les micro-gaps insignifiants)
        min_gap = atr * 0.3

        for i in range(2, len(df)):
            prev_close = closes[i-1]
            curr_open = opens[i]
            gap = curr_open - prev_close
            abs_gap = abs(gap)

            if abs_gap < min_gap:
                continue

            direction = "up" if gap > 0 else "down"

            # Déterminer si le gap a été refermé
            filled = False
            if direction == "up":
                # Gap haussier refermé si le prix est redescendu sous le close précédent
                if lows[i] <= prev_close and closes[i] < prev_close:
                    filled = True
            else:
                # Gap baissier refermé si le prix est remonté au-dessus du close précédent
                if highs[i] >= prev_close and closes[i] > prev_close:
                    filled = True

            # Catégoriser le type de gap
            gap_ratio = abs_gap / atr
            if gap_ratio < 1.0:
                gap_type = "common"
            elif gap_ratio < 2.0:
                gap_type = "breakaway"
            elif gap_ratio < 3.0:
                gap_type = "runaway"
            else:
                gap_type = "exhaustion"

            # Force basée sur la taille du gap
            strength = min(gap_ratio / 4.0, 1.0)

            gaps.append(PriceGap(
                tf=self.tf,
                direction=direction,
                gap_size=round(abs_gap, 2),
                open_price=curr_open,
                prev_close=prev_close,
                gap_percent=round(abs_gap / prev_close * 100, 3),
                index=i,
                time=df.index[i],
                gap_type=gap_type,
                filled=filled,
            ))

        return gaps

    # ── Discount / Premium ──────────────────────────────────────────────────

    def detect_discount_premium(self, df: pd.DataFrame) -> Optional[DiscountPremium]:
        """
        Calcule les zones de Discount (50% bas du range) et Premium (50% haut).
        Basé sur le range des 20 dernières bougies.
        """
        if df is None or len(df) < 20:
            return None

        window = df.tail(20)
        range_high = window["high"].max()
        range_low = window["low"].min()
        equilibrium = (range_high + range_low) / 2
        mid_discount = (equilibrium + range_low) / 2
        mid_premium = (equilibrium + range_high) / 2

        return DiscountPremium(
            tf=self.tf,
            equilibrium=equilibrium,
            discount_low=range_low,
            discount_high=equilibrium,
            premium_low=equilibrium,
            premium_high=range_high,
            range_high=range_high,
            range_low=range_low,
        )

    # ── Analyse complète ────────────────────────────────────────────────────

    def analyze(self, df: pd.DataFrame, current_price: float = 0.0) -> dict:
        """Analyse complète de tous les concepts ICT sur un DataFrame."""
        obs = self.detect_order_blocks(df)
        fvgs = self.detect_fvg(df)
        mss_list = self.detect_mss(df)
        liq = self.detect_liquidity(df)
        dp = self.detect_discount_premium(df)
        gaps = self.detect_price_gaps(df)

        # Filtrer les concepts trop éloignés du prix (> 35% d'écart par défaut)
        if current_price > 0:
            max_pct = self.cfg.concept_max_price_distance_pct
            obs = self._filter_by_price(obs, current_price, max_pct)
            fvgs = self._filter_by_price_fvg(fvgs, current_price, max_pct)
            mss_list = self._filter_by_price_mss(mss_list, current_price, max_pct)

        return {
            "order_blocks": obs,
            "fvgs": fvgs,
            "price_gaps": gaps,
            "mss": mss_list,
            "liquidity": liq,
            "discount_premium": dp,
        }

    def _filter_by_price(self, items: List, price: float, max_pct: float) -> List:
        """Filtre les items dont le prix est trop éloigné du prix actuel."""
        return [x for x in items if abs((x.high + x.low) / 2 - price) / price < max_pct]

    def _filter_by_price_fvg(self, items: List, price: float, max_pct: float) -> List:
        """Filtre les FVG trop éloignés."""
        return [x for x in items if abs((x.upper + x.lower) / 2 - price) / price < max_pct]

    def _filter_by_price_mss(self, items: List, price: float, max_pct: float) -> List:
        """Filtre les MSS trop éloignés."""
        return [x for x in items if abs(x.break_level - price) / price < max_pct]


class MultiTimeframeAnalyzer:
    """Analyse ICT sur plusieurs timeframes avec cohérence top-down."""

    def __init__(self):
        self.detectors: Dict[str, ICTConceptsDetector] = {}

    def get_detector(self, tf_name: str) -> ICTConceptsDetector:
        if tf_name not in self.detectors:
            self.detectors[tf_name] = ICTConceptsDetector(tf_name)
        return self.detectors[tf_name]

    def analyze_all(self, data: Dict[str, pd.DataFrame], current_price: float = 0.0) -> Dict[str, dict]:
        """Analyse tous les timeframes disponibles avec filtrage par prix."""
        results = {}
        for tf_name, df in data.items():
            if df is not None and len(df) > 10:
                detector = self.get_detector(tf_name)
                results[tf_name] = detector.analyze(df, current_price=current_price)
        return results

    # ── Key Levels (PDH, PDL, PWH, PWL, PMH, PML) ───────────────────────

    def detect_key_levels(self, data: Dict[str, pd.DataFrame]) -> List[KeyLevel]:
        """
        Détecte les niveaux clés ICT :
        - PDH/PDL : Plus Haut/Bas du Jour Précédent (depuis D1)
        - PWH/PWL : Plus Haut/Bas de la Semaine Précédente (depuis W1)
        - PMH/PML : Plus Haut/Bas du Mois Précédent (depuis MN1)
        
        Ces niveaux sont des aimants à liquidité. Le prix les cherche naturellement.
        """
        levels: List[KeyLevel] = []

        # PDH/PDL — depuis les données D1
        if "D1" in data and data["D1"] is not None and len(data["D1"]) >= 2:
            d1 = data["D1"]
            prev_day = d1.iloc[-2]
            current_day = d1.iloc[-1]

            pdh = float(prev_day["high"])
            pdl = float(prev_day["low"])

            # Sweep detection: le prix d'aujourd'hui a-t-il déjà dépassé ces niveaux ?
            pdh_swept = bool(current_day["high"] > pdh) if len(current_day) > 0 else False
            pdl_swept = bool(current_day["low"] < pdl) if len(current_day) > 0 else False

            levels.append(KeyLevel("PDH", pdh, d1.index[-2], "D1", 0.90,
                                   swept=pdh_swept, sweep_direction="up" if pdh_swept else None))
            levels.append(KeyLevel("PDL", pdl, d1.index[-2], "D1", 0.90,
                                   swept=pdl_swept, sweep_direction="down" if pdl_swept else None))

        # PWH/PWL — depuis les données W1
        if "W1" in data and data["W1"] is not None and len(data["W1"]) >= 2:
            w1 = data["W1"]
            prev_week = w1.iloc[-2]
            current_week = w1.iloc[-1]

            pwh = float(prev_week["high"])
            pwl = float(prev_week["low"])

            pwh_swept = bool(current_week["high"] > pwh) if len(current_week) > 0 else False
            pwl_swept = bool(current_week["low"] < pwl) if len(current_week) > 0 else False

            levels.append(KeyLevel("PWH", pwh, w1.index[-2], "W1", 0.95,
                                   swept=pwh_swept, sweep_direction="up" if pwh_swept else None))
            levels.append(KeyLevel("PWL", pwl, w1.index[-2], "W1", 0.95,
                                   swept=pwl_swept, sweep_direction="down" if pwl_swept else None))

        # PMH/PML — depuis les données MN1
        if "MN1" in data and data["MN1"] is not None and len(data["MN1"]) >= 2:
            mn1 = data["MN1"]
            prev_month = mn1.iloc[-2]
            current_month = mn1.iloc[-1]

            pmh = float(prev_month["high"])
            pml = float(prev_month["low"])

            pmh_swept = bool(current_month["high"] > pmh) if len(current_month) > 0 else False
            pml_swept = bool(current_month["low"] < pml) if len(current_month) > 0 else False

            levels.append(KeyLevel("PMH", pmh, mn1.index[-2], "MN1", 1.0,
                                   swept=pmh_swept, sweep_direction="up" if pmh_swept else None))
            levels.append(KeyLevel("PML", pml, mn1.index[-2], "MN1", 1.0,
                                   swept=pml_swept, sweep_direction="down" if pml_swept else None))

        return levels

    def detect_liquidity_from_key_levels(self, key_levels: List[KeyLevel]) -> List[LiquidityLevel]:
        """
        Convertit les key levels (PDH, PDL, etc.) en niveaux de liquidité BSL/SSL.
        PDH/PWH/PMH = BSL (le prix est attiré vers le haut pour chasser ces stops)
        PDL/PWL/PML = SSL (le prix est attiré vers le bas)
        """
        liquidity = []
        for kl in key_levels:
            liq_type = "BSL" if kl.level_type in ("PDH", "PWH", "PMH") else "SSL"
            liquidity.append(LiquidityLevel(
                tf=kl.source_tf,
                type=liq_type,
                level=kl.level,
                index=-1,
                time=kl.time,
                strength=kl.strength,
                swept=kl.swept,
            ))
        return liquidity

    def detect_sweeps_from_key_levels(
        self, key_levels: List[KeyLevel],
        data: Dict[str, pd.DataFrame],
        current_price: float,
    ) -> List[SweepSignal]:
        """
        Détecte les sweeps de key levels (Judas Swing / Turtle Soup).
        
        Un sweep SSL (PDL/PWL/PML cassé vers le bas puis prix remonte) = signal BUY.
        Un sweep BSL (PDH/PWH/PMH cassé vers le haut puis prix redescend) = signal SELL.
        """
        signals: List[SweepSignal] = []

        if not key_levels or current_price <= 0:
            return signals

        # Utiliser M15 ou M5 pour confirmer le sweep intraday
        confirm_tf = None
        confirm_df = None
        for tf in ["M15", "M5", "H1"]:
            if tf in data and data[tf] is not None and len(data[tf]) >= 5:
                confirm_tf = tf
                confirm_df = data[tf]
                break

        if confirm_df is None:
            confirm_df = data.get("D1")
            confirm_tf = "D1"
        if confirm_df is None:
            return signals

        recent = confirm_df.tail(2)  # Seulement les 2 dernières barres pour éviter faux positifs
        recent_high = float(recent["high"].max())
        recent_low = float(recent["low"].min())
        recent_close = float(recent["close"].iloc[-1])

        for kl in key_levels:
            if kl.swept:
                continue

            # SSL Sweep → BUY signal (prix passe sous PDL/PWL/PML puis remonte)
            if kl.liquidity_type == "SSL":
                if recent_low <= kl.level and recent_close > kl.level:
                    strength = min(abs(kl.level - recent_low) / (kl.level * 0.005), 1.0)
                    detail = (
                        f"🎯 SWEEP SSL {kl.level_type} ({kl.label}) — "
                        f"Prix a cassé {kl.level:.1f}$ vers le bas puis est remonté à {current_price:.1f}$ "
                        f"→ Signal LONG (Judas Swing / Turtle Soup)"
                    )
                    signals.append(SweepSignal(
                        level=kl,
                        direction="buy",
                        sweep_bar_index=-1,
                        sweep_bar_time=recent.index[-1],
                        confirmation=True,
                        strength=strength,
                        detail=detail,
                    ))
                    kl.swept = True
                    kl.sweep_direction = "down"

            # BSL Sweep → SELL signal (prix passe au-dessus PDH/PWH/PMH puis redescend)
            elif kl.liquidity_type == "BSL":
                if recent_high >= kl.level and recent_close < kl.level:
                    strength = min(abs(recent_high - kl.level) / (kl.level * 0.005), 1.0)
                    detail = (
                        f"🎯 SWEEP BSL {kl.level_type} ({kl.label}) — "
                        f"Prix a cassé {kl.level:.1f}$ vers le haut puis est redescendu à {current_price:.1f}$ "
                        f"→ Signal SHORT (Judas Swing / Turtle Soup)"
                    )
                    signals.append(SweepSignal(
                        level=kl,
                        direction="sell",
                        sweep_bar_index=-1,
                        sweep_bar_time=recent.index[-1],
                        confirmation=True,
                        strength=strength,
                        detail=detail,
                    ))
                    kl.swept = True
                    kl.sweep_direction = "up"

        return signals

    # ── Bias Matrix (avec filtrage prix + recence) ──────────────────────

    def get_bias_matrix(
        self, results: Dict[str, dict], current_price: float = 0.0
    ) -> Dict[str, str]:
        """
        Calcule le bias pour chaque timeframe basé sur les concepts détectés.
        Les concepts sont pondérés par leur force et filtrés par proximité de prix.
        Retourne: {"MN1": "bearish", "W1": "bearish", "D1": "neutral", ...}
        """
        bias_map = {}
        for tf_name, analysis in results.items():
            bullish_score = 0.0
            bearish_score = 0.0

            # Order Blocks (pondérés par force)
            for ob in analysis.get("order_blocks", []):
                weight = ob.strength * 2
                if ob.type == "bullish":
                    bullish_score += weight
                else:
                    bearish_score += weight

            # FVGs (pondérés par force)
            for fvg in analysis.get("fvgs", []):
                weight = fvg.strength * 1.5
                if fvg.type == "bullish":
                    bullish_score += weight
                else:
                    bearish_score += weight

            # MSS (pondérés par force)
            for mss in analysis.get("mss", []):
                weight = mss.strength * 3
                if mss.direction == "bullish":
                    bullish_score += weight
                else:
                    bearish_score += weight

            # Décision
            if bullish_score > bearish_score + 1.0:
                bias_map[tf_name] = "bullish"
            elif bearish_score > bullish_score + 1.0:
                bias_map[tf_name] = "bearish"
            else:
                bias_map[tf_name] = "neutral"

        return bias_map

    def detect_higher_timeframe_conflict(self, bias_map: Dict[str, str]) -> List[str]:
        """Détecte les conflits entre timeframes."""
        conflicts = []
        ordered = ["MN1", "W1", "D1", "H4", "H1", "M15", "M5"]

        for i in range(len(ordered) - 1):
            if ordered[i] in bias_map and ordered[i+1] in bias_map:
                b1 = bias_map[ordered[i]]
                b2 = bias_map[ordered[i+1]]
                if (b1 == "bullish" and b2 == "bearish") or \
                   (b1 == "bearish" and b2 == "bullish"):
                    conflicts.append(f"{ordered[i]}:{b1} vs {ordered[i+1]}:{b2}")
        return conflicts
