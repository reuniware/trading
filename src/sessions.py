"""
Détection des sessions de trading (Kill Zones) ICT :
- Session Asiatique
- Session Londres
- Session New York
- Silver Bullet (09:30-11:00 NY)
- London Close / New York Open
- Conformité killzone (le prix fait-il ce qui est attendu ?)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict
from dataclasses import dataclass

import pandas as pd

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


@dataclass
class KillzoneConformity:
    """
    Vérifie si l'action du prix est conforme au comportement attendu
    pour la killzone active (méthodologie ICT).
    """
    killzone_name: str          # "asian", "london", "newyork", "silver_bullet"
    killzone_label: str         # "Asie", "Londres", "New York", "Silver Bullet NY"
    is_active: bool             # La killzone est-elle active ?
    expected_behavior: str      # Comportement attendu selon ICT
    actual_behavior: str        # Comportement observé
    conformity: str             # "conforme" | "partiel" | "non_conforme" | "inactif"
    conformity_score: float     # 0.0 à 1.0
    details: List[str]          # Détails des vérifications
    warning: str = ""           # Avertissement si non-conforme

    def conformity_label(self) -> str:
        labels = {
            "conforme": "✅ Conforme",
            "partiel": "⚠️ Partiellement conforme",
            "non_conforme": "❌ Non conforme",
            "inactif": "⏳ Inactif",
        }
        return labels.get(self.conformity, self.conformity)

    def conformity_color(self) -> str:
        colors = {
            "conforme": "#00ff88",
            "partiel": "#ffaa00",
            "non_conforme": "#ff4444",
            "inactif": "#888888",
        }
        return colors.get(self.conformity, "#888888")


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

    def check_killzone_conformity(
        self,
        data: Optional[Dict[str, "pd.DataFrame"]] = None,
        sweep_signals: Optional[List] = None,
        pd_array_range: float = 50.0,
    ) -> KillzoneConformity:
        """
        Vérifie si l'action du prix est conforme au comportement attendu
        pour la killzone active selon la méthodologie ICT.

        Chaque killzone a un comportement type :
        - Asie : Range étroit, faible volatilité, consolidation → le prix pose les niveaux du jour
        - Londres : Trend directionnel, fort volume, volatilité → cassure des ranges asiatiques
        - New York : Pic de liquidité, sweeps, reversals → chasse aux stops
        - Silver Bullet : Impulsion puissante, 1.272+ PD Array → trade de précision
        """
        all_sessions = self.get_all_sessions()
        active = [s for s in all_sessions if s.active]

        if not active:
            return KillzoneConformity(
                killzone_name="none",
                killzone_label="Aucune",
                is_active=False,
                expected_behavior="Aucune killzone active",
                actual_behavior="Marché au ralenti",
                conformity="inactif",
                conformity_score=0.0,
                details=["Aucune killzone ICT active actuellement."],
            )

        # Prendre la killzone la plus prioritaire
        priority = ["silver_bullet", "newyork", "london", "asian"]
        primary = None
        for name in priority:
            for s in active:
                if s.name == name:
                    primary = s
                    break
            if primary:
                break
        if not primary:
            primary = active[0]

        # Comportements attendus par killzone
        expectations = {
            "asian": {
                "expected": "Range étroit, faible volatilité, consolidation. Le prix pose les niveaux du jour (PDH/PDL).",
                "checks": ["range_etroit", "faible_volatilite", "consolidation"],
            },
            "london": {
                "expected": "Trend directionnel, forte volatilité, cassure du range asiatique. Gros volume.",
                "checks": ["trend_directionnel", "forte_volatilite", "cassure_range"],
            },
            "newyork": {
                "expected": "Pic d'activité, chasse de liquidité (BSL/SSL), reversals. Chevauchement Londres 13-16h.",
                "checks": ["liquidite_chassee", "forte_volatilite", "reversal_possible"],
            },
            "silver_bullet": {
                "expected": "Impulsion puissante et précise, mouvement 1.272+ PD Array. Fenêtre de 90min.",
                "checks": ["impulsion_forte", "mouvement_directionnel", "extension_fibonacci"],
            },
        }

        exp = expectations.get(primary.name, expectations["asian"])
        details: List[str] = []
        score = 0.0
        total_checks = len(exp["checks"])
        passed = 0

        # Seuils adaptatifs basés sur le PD Array range (pas de % fixe du prix)
        tight_range_max = pd_array_range * 0.5   # Range étroit = < 50% du PD range
        high_vol_min = pd_array_range * 1.0       # Forte volatilité = > 100% du PD range

        # Analyser les données si disponibles
        if data:
            # Utiliser M5 ou M15 pour l'analyse intraday
            df = None
            for tf in ["M5", "M15", "H1"]:
                if tf in data and data[tf] is not None and len(data[tf]) >= 10:
                    df = data[tf]
                    break

            if df is not None and len(df) >= 10:
                recent = df.tail(10)
                closes = recent["close"].values
                highs = recent["high"].values
                lows = recent["low"].values
                volumes = recent["volume"].values if "volume" in recent.columns else None

                range_val = float(highs.max() - lows.min())
                body_sizes = abs(closes - recent["open"].values) if "open" in recent.columns else None

                # ---- Vérifications communes ----

                # 1. Range étroit ? (range < 50% du PD Array range)
                is_tight_range = range_val < tight_range_max

                # 2. Forte volatilité ? (range > 100% du PD Array range)
                is_high_vol = range_val > high_vol_min

                # 3. Trend directionnel ? (HH/HL ou LH/LL clair)
                has_trend = False
                trend_direction = "neutre"
                if len(highs) >= 6:
                    first_high = highs[:3].max()
                    last_high = highs[-3:].max()
                    first_low = lows[:3].min()
                    last_low = lows[-3:].min()
                    if last_high > first_high and last_low > first_low:
                        has_trend = True
                        trend_direction = "haussière"
                    elif last_high < first_high and last_low < first_low:
                        has_trend = True
                        trend_direction = "baissière"

                # 4. Consolidation ? (pas de trend + range étroit)
                is_consolidating = not has_trend and is_tight_range

                # 5. Sweeps de liquidité détectés ?
                has_sweeps = bool(sweep_signals) if sweep_signals else False

                # 6. Impulsion forte ? (body > 2x précédent)
                has_impulse = False
                if body_sizes is not None and len(body_sizes) >= 2:
                    if body_sizes[-1] > body_sizes[-2] * 2:
                        has_impulse = True

                # 7. Volume élevé ? (volume > 1.5x moyenne)
                high_volume = False
                if volumes is not None and len(volumes) >= 5:
                    avg_vol = volumes[:-1].mean() if len(volumes) > 1 else volumes[0]
                    if avg_vol > 0 and volumes[-1] > avg_vol * 1.5:
                        high_volume = True

                # ---- Vérifications spécifiques par killzone ----

                if primary.name == "asian":
                    if is_tight_range:
                        details.append(f"✅ Range étroit ({range_val:.1f}$ vs PD range {pd_array_range:.1f}$) — typique de l'Asie")
                        passed += 1
                    else:
                        details.append(f"⚠️ Range large ({range_val:.1f}$ vs PD range {pd_array_range:.1f}$) — inhabituel pour l'Asie")

                    if is_consolidating:
                        details.append("✅ Consolidation détectée — le prix pose les niveaux")
                        passed += 1
                    else:
                        details.append("⚠️ Mouvement directionnel — atypique pour l'Asie")

                    if not high_volume:
                        details.append("✅ Volume faible — conforme au profil Asie")
                        passed += 1
                    else:
                        details.append("⚠️ Volume élevé — pourrait annoncer une cassure")

                elif primary.name == "london":
                    if has_trend:
                        details.append(f"✅ Trend {trend_direction} détecté — typique de Londres")
                        passed += 1
                    else:
                        details.append("⚠️ Pas de trend clair — Londres devrait être directionnel")

                    if is_high_vol:
                        details.append(f"✅ Forte volatilité ({range_val:.1f}$ vs PD range {pd_array_range:.1f}$) — conforme à Londres")
                        passed += 1
                    else:
                        details.append(f"⚠️ Volatilité modérée ({range_val:.1f}$ vs PD range {pd_array_range:.1f}$) — Londres attend plus d'action")

                    if high_volume:
                        details.append("✅ Volume élevé — participation institutionnelle")
                        passed += 1
                    else:
                        details.append("⚠️ Volume normal — attente de confirmation")

                elif primary.name == "newyork":
                    if has_sweeps:
                        details.append(f"✅ {len(sweep_signals)} sweep(s) de liquidité détecté(s) — typique de NY")
                        passed += 1
                    else:
                        details.append("⚠️ Aucun sweep détecté — NY devrait chasser la liquidité")

                    if is_high_vol:
                        details.append(f"✅ Forte volatilité ({range_val:.1f}$ vs PD range {pd_array_range:.1f}$) — pic d'activité NY")
                        passed += 1
                    else:
                        details.append("⚠️ Volatilité modérée — NY devrait être le pic")

                    # NY = potentiel de reversal
                    if has_trend and has_sweeps:
                        details.append("✅ Configuration reversal NY possible (trend + sweep)")
                        passed += 1
                    else:
                        details.append("ℹ️ Surveiller les signes de reversal NY (Judas Swing)")
                        passed += 0  # neutre, ne compte pas
                        total_checks -= 1

                elif primary.name == "silver_bullet":
                    if has_impulse:
                        details.append("✅ Impulsion forte détectée — typique du Silver Bullet")
                        passed += 1
                    else:
                        details.append("⚠️ Pas d'impulsion claire — Silver Bullet attend un mouvement puissant")

                    if has_trend:
                        details.append(f"✅ Mouvement directionnel {trend_direction} — Silver Bullet précis")
                        passed += 1
                    else:
                        details.append("⚠️ Pas de direction claire — le Silver Bullet est directionnel")

                    if is_high_vol:
                        details.append(f"✅ Range expansif ({range_val:.1f}$ vs PD range {pd_array_range:.1f}$) — extension 1.272+ possible")
                        passed += 1
                    else:
                        details.append(f"⚠️ Range modéré ({range_val:.1f}$ vs PD range {pd_array_range:.1f}$) — attendre l'expansion")

        else:
            details.append("ℹ️ Données de prix non disponibles pour l'analyse de conformité")
            total_checks = 0

        # Calcul du score
        if total_checks > 0:
            score = passed / total_checks

        # Déterminer la conformité
        if score >= 0.66:
            conformity = "conforme"
        elif score >= 0.33:
            conformity = "partiel"
        else:
            conformity = "non_conforme"

        # Construire l'alerte si non conforme
        warning = ""
        if conformity == "non_conforme":
            warning = (
                f"⚠️ Le prix ne suit pas le comportement attendu pour {primary.label}. "
                f"Soit la killzone est atypique aujourd'hui, soit un événement externe perturbe le marché. "
                f"Prudence recommandée."
            )
        elif conformity == "partiel":
            warning = (
                f"⚠️ Le prix suit partiellement le comportement {primary.label}. "
                f"Attendre confirmation avant d'engager une position."
            )

        # Description du comportement observé
        if data and df is not None:
            if has_trend:
                actual = f"Trend {trend_direction} (range: {range_val:.1f}$)"
            elif is_consolidating:
                actual = f"Consolidation (range: {range_val:.1f}$)"
            else:
                actual = f"Range: {range_val:.1f}$, {'sweeps détectés' if has_sweeps else 'pas de sweep'}"
        else:
            actual = "Données insuffisantes"

        return KillzoneConformity(
            killzone_name=primary.name,
            killzone_label=primary.label,
            is_active=True,
            expected_behavior=exp["expected"],
            actual_behavior=actual,
            conformity=conformity,
            conformity_score=round(score, 2),
            details=details,
            warning=warning,
        )
