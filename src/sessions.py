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

    def get_all_sessions(self) -> List[ActiveSession]:
        """Retourne l'état de toutes les sessions."""
        results = []
        for session in SESSIONS:
            active = self.is_session_active(session)
            results.append(ActiveSession(
                name=session.name,
                label=session.label,
                open_utc=session.open_utc,
                close_utc=session.close_utc,
                color=session.color,
                active=active,
            ))

        # Silver Bullet
        sb_active = self.is_silver_bullet_active()
        results.append(ActiveSession(
            name="silver_bullet",
            label=SILVER_BULLET["label"],
            open_utc=SILVER_BULLET["open_utc"],
            close_utc=SILVER_BULLET["close_utc"],
            color=SILVER_BULLET["color"],
            active=sb_active,
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
    def get_session_range(symbol: str = "XAUUSD") -> Dict:
        """
        Retourne le range (haut/bas) de la session asiatique pour le calcul des zones ICT.
        """
        return {"high": None, "low": None}  # Rempli par le data engine
