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

    def analyze(self, df: pd.DataFrame) -> dict:
        """Analyse complète de tous les concepts ICT sur un DataFrame."""
        return {
            "order_blocks": self.detect_order_blocks(df),
            "fvgs": self.detect_fvg(df),
            "mss": self.detect_mss(df),
            "liquidity": self.detect_liquidity(df),
            "discount_premium": self.detect_discount_premium(df),
        }


class MultiTimeframeAnalyzer:
    """Analyse ICT sur plusieurs timeframes avec cohérence top-down."""

    def __init__(self):
        self.detectors: Dict[str, ICTConceptsDetector] = {}

    def get_detector(self, tf_name: str) -> ICTConceptsDetector:
        if tf_name not in self.detectors:
            self.detectors[tf_name] = ICTConceptsDetector(tf_name)
        return self.detectors[tf_name]

    def analyze_all(self, data: Dict[str, pd.DataFrame]) -> Dict[str, dict]:
        """Analyse tous les timeframes disponibles."""
        results = {}
        for tf_name, df in data.items():
            if df is not None and len(df) > 10:
                detector = self.get_detector(tf_name)
                results[tf_name] = detector.analyze(df)
        return results

    def get_bias_matrix(self, results: Dict[str, dict]) -> Dict[str, str]:
        """
        Calcule le bias pour chaque timeframe basé sur les concepts détectés.
        Retourne: {"MN1": "bearish", "W1": "bearish", "D1": "neutral", ...}
        """
        bias_map = {}
        for tf_name, analysis in results.items():
            bullish_score = 0.0
            bearish_score = 0.0

            # Order Blocks
            for ob in analysis.get("order_blocks", []):
                if ob.type == "bullish":
                    bullish_score += ob.strength * 2
                else:
                    bearish_score += ob.strength * 2

            # FVGs
            for fvg in analysis.get("fvgs", []):
                if fvg.type == "bullish":
                    bullish_score += fvg.strength * 1.5
                else:
                    bearish_score += fvg.strength * 1.5

            # MSS
            for mss in analysis.get("mss", []):
                if mss.direction == "bullish":
                    bullish_score += mss.strength * 3
                else:
                    bearish_score += mss.strength * 3

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
