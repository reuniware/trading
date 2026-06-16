"""
Configuration centralisée pour le système de trading ICT.
"""

import MetaTrader5 as mt5
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ─── Symboles ───────────────────────────────────────────────────────────────
SYMBOLS = ["XAUUSD"]  # Ajouter d'autres symboles si besoin

# ─── Timeframes ─────────────────────────────────────────────────────────────
TIMEFRAMES = {
    "MN1": mt5.TIMEFRAME_MN1,
    "W1":  mt5.TIMEFRAME_W1,
    "D1":  mt5.TIMEFRAME_D1,
    "H4":  mt5.TIMEFRAME_H4,
    "H1":  mt5.TIMEFRAME_H1,
    "M15": mt5.TIMEFRAME_M15,
    "M5":  mt5.TIMEFRAME_M5,
    "M1":  mt5.TIMEFRAME_M1,
}

TIMEFRAME_NAMES = list(TIMEFRAMES.keys())

# Ordre hiérarchique (du plus haut au plus bas)
TIMEFRAME_HIERARCHY = ["MN1", "W1", "D1", "H4", "H1", "M15", "M5", "M1"]

# Mapping des noms lisibles
TIMEFRAME_LABELS = {
    "MN1": "Mensuel",
    "W1":  "Hebdo",
    "D1":  "Daily",
    "H4":  "4H",
    "H1":  "1H",
    "M15": "15M",
    "M5":  "5M",
    "M1":  "1M",
}

# Combien de barres charger par défaut
TIMEFRAME_BARS = {
    "MN1": 60,
    "W1":  104,
    "D1":  365,
    "H4":  500,
    "H1":  500,
    "M15": 500,
    "M5":  500,
    "M1":  200,
}

# ─── Sessions / Kill Zones (format: (heure_ouverture, heure_fermeture) en UTC) ─
@dataclass
class Session:
    name: str
    label: str
    open_utc: int
    close_utc: int
    color: str

SESSIONS: List[Session] = [
    Session("asian",     "Asie",       22, 8,  "#FFD700"),
    Session("london",    "Londres",     7, 16, "#1E90FF"),
    Session("newyork",   "New York",   13, 21, "#32CD32"),
]

SILVER_BULLET = {
    "label": "Silver Bullet NY",
    "open_utc": 13,   # 09:30 NY = 13:30 UTC (été) / 14:30 UTC (hiver)
    "close_utc": 15,  # 11:00 NY = 15:00 UTC (été) / 16:00 UTC (hiver)
    "color": "#FF4500",
}

# ─── Paramètres de Risque ───────────────────────────────────────────────────
@dataclass
class RiskConfig:
    max_risk_percent: float = 1.0       # Risque max par trade (% du compte)
    max_daily_loss_percent: float = 3.0 # Perte max journalière
    max_open_positions: int = 3         # Positions max simultanées
    default_r_multiple: float = 2.5     # R:R minimum par défaut
    min_r_multiple: float = 2.0         # R:R minimum absolu
    position_sizing_method: str = "fixed_risk"  # fixed_risk | fixed_lot | kelly
    default_lot_size: float = 0.01      # Lot size par défaut (en fixed_lot)

# ─── Paramètres ICT ─────────────────────────────────────────────────────────
@dataclass
class ICTConfig:
    # FVG
    fvg_min_body_ratio: float = 0.3     # Ratio corps/ombre min pour FVG
    fvg_max_gap_bars: int = 3           # Max barres d'écart pour FVG
    
    # Order Block
    ob_lookback: int = 20               # Barres à scruter pour OB
    ob_min_impulse_ratio: float = 0.5   # Ratio impulsion min pour OB
    
    # MSS / BOS
    mss_lookback: int = 30              # Barres à scruter pour MSS
    mss_min_break_percent: float = 0.1  # % min de cassure pour MSS
    
    # Liquidity
    liq_lookback: int = 50              # Barres à scruter pour liquidité
    liq_sweep_percent: float = 0.05     # % de sweep pour détection

    # Key Levels (PDH/PDL/PWH/PWL/PMH/PML)
    key_level_max_distance_pct: float = 0.35  # % max du prix pour considérer un key level
    key_level_sweep_threshold: float = 0.1    # % min pour confirmer un sweep

    # Filtrage concepts obsolètes
    concept_max_price_distance_pct: float = 0.35  # % max d'écart prix pour les OB/FVG/MSS

# ─── Instances globales ────────────────────────────────────────────────────
RISK = RiskConfig()
ICT = ICTConfig()
