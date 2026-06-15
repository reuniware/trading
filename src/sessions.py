"""
Détection des sessions de trading (Kill Zones) ICT :
- Session Asiatique
- Session Londres
- Session New York
- Silver Bullet (09:30-11:00 NY)
- London Close / New York Open
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
from dataclasses import dataclass

from .config import SESSIONS, SILVER_BULLET

logger = logging.getLogger("Sessions")


@dataclass
class ActiveSession:
    name: str
    label: str
    open_utc: int
    close_utc: int
    color: str
    active: bool
    time_until_open: Optional[str] = None
    time_until_close: Optional[str] = None


class SessionDetector:
    """Détecte les sessions de trading actives."""

    # Décalage horaire (UTC+2 en été pour Paris)
    UTC_OFFSET = 2  # UTC+2 en été

    @staticmethod
    def get_utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def get_local_now() -> datetime:
        """Heure locale (Paris = UTC+2 en été)."""
        return datetime.now()

    def is_session_active(self, session) -> bool:
        """Vérifie si une session est active maintenant."""
        utc_hour = self.get_utc_now().hour
        open_h = session["open_utc"] if isinstance(session, dict) else session.open_utc
        close_h = session["close_utc"] if isinstance(session, dict) else session.close_utc

        if open_h <= close_h:
            return open_h <= utc_hour < close_h
        else:  # Session chevauchant minuit (ex: Asie 22h-8h)
            return utc_hour >= open_h or utc_hour < close_h

    def is_silver_bullet_active(self) -> bool:
        """Silver Bullet NY : 09:30-11:00 NY = 13:30-15:00 UTC (été)."""
        now = self.get_utc_now()
        hour = now.hour
        minute = now.minute
        open_time = SILVER_BULLET["open_utc"] * 60 + 30  # +30 min
        close_time = SILVER_BULLET["close_utc"] * 60
        current_time = hour * 60 + minute
        return open_time <= current_time < close_time

    def _format_countdown(self, minutes: int) -> str:
        """Formate un nombre de minutes en texte lisible."""
        if minutes <= 0:
            return "Maintenant"
        if minutes < 60:
            return f"{minutes} min"
        h, m = divmod(minutes, 60)
        if h < 24:
            return f"{h}h{m:02d}"
        return f"{h//24}j{h%24}h"

    def get_all_sessions(self) -> List[ActiveSession]:
        """Retourne l'état de toutes les sessions avec décomptes."""
        results = []
        now = self.get_utc_now()
        current_minutes = now.hour * 60 + now.minute

        for session in SESSIONS:
            active = self.is_session_active(session)
            open_m = session.open_utc * 60
            close_m = session.close_utc * 60

            if active:
                # Temps restant avant fermeture (gère sessions qui chevauchent minuit)
                remaining = (session.close_utc * 60 - current_minutes) % (24 * 60)
                time_until_close = self._format_countdown(remaining if remaining > 0 else 24 * 60)
                time_until_open = None
            else:
                # Temps avant ouverture
                until_open = (session.open_utc * 60 - current_minutes) % (24 * 60)
                time_until_open = self._format_countdown(until_open if until_open > 0 else 24 * 60)
                time_until_close = None

            results.append(ActiveSession(
                name=session.name,
                label=session.label,
                open_utc=session.open_utc,
                close_utc=session.close_utc,
                color=session.color,
                active=active,
                time_until_open=time_until_open,
                time_until_close=time_until_close,
            ))

        # Silver Bullet
        sb_active = self.is_silver_bullet_active()
        if sb_active:
            # Fermeture dans X minutes
            sb_close_m = SILVER_BULLET["close_utc"] * 60
            sb_remaining = sb_close_m - current_minutes
            sb_time_close = self._format_countdown(max(0, sb_remaining))
            results.append(ActiveSession(
                name="silver_bullet",
                label=SILVER_BULLET["label"],
                open_utc=SILVER_BULLET["open_utc"],
                close_utc=SILVER_BULLET["close_utc"],
                color=SILVER_BULLET["color"],
                active=True,
                time_until_close=sb_time_close,
            ))
        else:
            # Prochaine ouverture SB
            sb_open_m = SILVER_BULLET["open_utc"] * 60 + 30
            sb_until = (sb_open_m - current_minutes) % (24 * 60)
            results.append(ActiveSession(
                name="silver_bullet",
                label=SILVER_BULLET["label"],
                open_utc=SILVER_BULLET["open_utc"],
                close_utc=SILVER_BULLET["close_utc"],
                color=SILVER_BULLET["color"],
                active=False,
                time_until_open=self._format_countdown(sb_until),
            ))

        return results

    def get_active_sessions(self) -> List[ActiveSession]:
        """Retourne uniquement les sessions actives."""
        return [s for s in self.get_all_sessions() if s.active]

    def get_next_session(self) -> Optional[ActiveSession]:
        """Trouve la prochaine session à venir."""
        all_sessions = self.get_all_sessions()
        utc_hour = self.get_utc_now().hour
        next_session = None
        min_diff = 24

        for s in all_sessions:
            if s.active:
                continue
            # Calculer la différence
            diff = (s.open_utc - utc_hour) % 24
            if 0 < diff < min_diff:
                min_diff = diff
                next_session = s

        return next_session

    def is_killzone_active(self) -> bool:
        """Vérifie si on est dans une kill zone active (London ou NY)."""
        active = self.get_active_sessions()
        names = [s.name for s in active]
        return "london" in names or "newyork" in names

    def get_session_stats(self) -> Dict:
        """Statistiques des sessions pour le dashboard."""
        active = self.get_active_sessions()
        next_s = self.get_next_session()

        return {
            "active_sessions": active,
            "next_session": next_s,
            "silver_bullet_active": self.is_silver_bullet_active(),
            "local_time": self.get_local_now().strftime("%H:%M"),
            "utc_time": self.get_utc_now().strftime("%H:%M"),
            "is_killzone_active": self.is_killzone_active(),
        }

    @staticmethod
    def compute_macro_context(
        bias_matrix: Dict[str, str],
        proximity: Dict,
        session_stats: Dict,
    ) -> Dict:
        """
        Calcule le contexte macro ICT à partir :
        - Du bias HTF (MN1, W1, D1)
        - De la position du prix (Premium/Discount)
        - De la killzone active
        
        Retourne un dict avec :
        - macro_bias : "bullish" | "bearish" | "neutral"
        - macro_label : description lisible
        - price_zone : "discount" | "premium" | "equilibrium"
        - active_killzone : nom de la killzone active
        - silver_bullet : bool
        """
        # 1. Déterminer le bias macro (poids HTF: MN1 > W1 > D1)
        htf_bias = "neutral"
        for tf in ["MN1", "W1", "D1"]:
            if tf in bias_matrix and bias_matrix[tf] != "neutral":
                htf_bias = bias_matrix[tf]
                break

        # 2. Position du prix dans le cycle ICT
        price_zone = "equilibrium"
        if proximity:
            if "Discount" in proximity and any(a.is_entry_zone for a in proximity["Discount"]):
                price_zone = "discount"
            elif "Premium" in proximity and any(a.is_entry_zone for a in proximity["Premium"]):
                price_zone = "premium"

        # 3. Killzone active
        active = session_stats.get("active_sessions", [])
        active_names = [s.name for s in active]
        killzone_names = {
            "asian": "Asie",
            "london": "Londres",
            "newyork": "New York",
            "silver_bullet": "Silver Bullet NY",
        }
        active_killzone = ""
        for name in ["silver_bullet", "newyork", "london", "asian"]:
            if name in active_names:
                active_killzone = killzone_names.get(name, name)
                break

        # 4. Label macro
        bias_labels = {
            "bullish": "HAUSSIÈRE 🟢",
            "bearish": "BAISSIÈRE 🔴",
            "neutral": "NEUTRE 🟡",
        }
        zone_labels = {
            "discount": "Zone Discount (achat)",
            "premium": "Zone Premium (vente)",
            "equilibrium": "Équilibre",
        }

        sb_str = " — 🔥 Silver Bullet active !" if session_stats.get("silver_bullet_active") else ""
        kz_str = f" — {active_killzone}" if active_killzone else ""
        
        macro_label = f"MACRO {bias_labels.get(htf_bias, 'NEUTRE 🟡')} — {zone_labels.get(price_zone, 'Équilibre')}{kz_str}{sb_str}"

        return {
            "macro_bias": htf_bias,
            "macro_label": macro_label,
            "price_zone": price_zone,
            "active_killzone": active_killzone,
            "silver_bullet": session_stats.get("silver_bullet_active", False),
        }

    @staticmethod
    def get_session_range(symbol: str = "XAUUSD") -> Dict:
        """
        Retourne le range (haut/bas) de la session asiatique pour le calcul des zones ICT.
        """
        return {"high": None, "low": None}  # Rempli par le data engine
