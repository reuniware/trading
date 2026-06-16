"""
Suivi des setups de trading ICT.
Enregistre les setups détectés, vérifie la direction prise par le prix
par rapport aux TP/SL, et fournit des statistiques de performance.

Fonctionne en mémoire (session Streamlit) + persistance JSON optionnelle.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger("SetupTracker")


@dataclass
class TrackedSetup:
    """Un setup de trading suivi dans le temps."""
    id: str
    symbol: str
    direction: str           # "long" | "short"
    entry_low: float
    entry_high: float
    stop_loss: float
    target_1: float
    target_2: Optional[float] = None
    target_3: Optional[float] = None
    detected_at: str = ""    # Timestamp ISO
    detected_price: float = 0.0
    strength: float = 0.0
    reason: str = ""
    source: str = ""         # "signal", "proximity", "sweep", "keylevel"
    status: str = "active"   # "active" | "win_tp1" | "win_tp2" | "win_tp3" | "loss" | "expired" | "never_triggered"
    outcome_price: Optional[float] = None
    outcome_at: Optional[str] = None
    bars_to_outcome: int = 0
    price_path: List[float] = field(default_factory=list)  # Historique des prix

    @property
    def entry_mid(self) -> float:
        return (self.entry_low + self.entry_high) / 2

    def risk_reward(self) -> float:
        """R:R du setup (TP1)."""
        if self.stop_loss == 0.0:
            return 0.0
        entry = self.entry_mid
        if self.direction == "long":
            risk = entry - self.stop_loss
            reward = self.target_1 - entry
        else:
            risk = self.stop_loss - entry
            reward = entry - self.target_1
        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)

    def check_outcome(self, current_price: float, current_high: float, current_low: float) -> Optional[str]:
        """
        Vérifie si le prix a touché TP ou SL.
        Retourne "tp1", "tp2", "tp3", "sl", ou None si toujours actif.
        """
        if self.status != "active":
            return None

        if self.direction == "long":
            # LONG : TP3 > TP2 > TP1 — vérifier le plus grand d'abord
            if self.target_3 and current_high >= self.target_3:
                return "tp3"
            if self.target_2 and current_high >= self.target_2:
                return "tp2"
            if current_high >= self.target_1:
                return "tp1"
            if current_low <= self.stop_loss:
                return "sl"
        else:
            # SHORT : TP3 < TP2 < TP1 — vérifier le plus petit d'abord
            if self.target_3 and current_low <= self.target_3:
                return "tp3"
            if self.target_2 and current_low <= self.target_2:
                return "tp2"
            if current_low <= self.target_1:
                return "tp1"
            if current_high >= self.stop_loss:
                return "sl"

        return None

    def get_status_label(self) -> str:
        """Label lisible du statut."""
        labels = {
            "active": "🔄 Actif",
            "win_tp1": "✅ TP1",
            "win_tp2": "✅ TP2",
            "win_tp3": "✅ TP3",
            "loss": "❌ SL",
            "expired": "⏰ Expiré",
            "never_triggered": "⏳ Non déclenché",
        }
        return labels.get(self.status, self.status)

    def get_direction_label(self) -> str:
        return "🟢 LONG" if self.direction == "long" else "🔴 SHORT"


class SetupTracker:
    """
    Traqueur de setups ICT.
    Enregistre les setups, vérifie leur outcome, fournit des stats.
    """

    def __init__(self, storage_path: Optional[str] = None):
        self.setups: Dict[str, TrackedSetup] = {}
        self.storage_path = storage_path
        self._max_setups = 500          # Garder max 500 setups en mémoire
        self._expiry_hours = 168         # Expiration après 7 jours
        if storage_path:
            self._load()

    def log_setups(
        self,
        setups: List[Any],  # List[ProximitySetup] ou List[TradeSignal]
        current_price: float,
        symbol: str = "XAUUSD",
        source: str = "proximity",
    ) -> List[str]:
        """
        Enregistre de nouveaux setups pour suivi.
        Évite les doublons (même direction + prix proche + détection récente).
        Retourne les IDs créés.
        """
        new_ids = []
        now = datetime.now().isoformat()

        for s in setups:
            # Éviter les doublons : vérifier si un setup similaire existe déjà
            if self._is_duplicate(s, current_price):
                continue

            direction = getattr(s, 'direction', 'long')
            # Support both TradeSignal and ProximitySetup
            if hasattr(s, 'entry_zone_low'):  # TradeSignal
                entry_low = s.entry_zone_low
                entry_high = s.entry_zone_high
                sl = s.stop_loss
                tp1 = s.target_1
                tp2 = s.target_2
                tp3 = s.target_3
                strength = s.score / 100.0 if hasattr(s, 'score') else 0.5
                reason = getattr(s, 'reason', '')
                # Convert buy/sell to long/short
                direction = "long" if direction == "buy" else "short" if direction == "sell" else direction
            else:  # ProximitySetup
                entry_low = s.entry_low
                entry_high = s.entry_high
                sl = s.stop_loss
                tp1 = s.target_1
                tp2 = s.target_2
                tp3 = s.target_3
                strength = getattr(s, 'strength', 0.5)
                reason = getattr(s, 'reason', '')

            setup_id = str(uuid4())[:8]
            tracked = TrackedSetup(
                id=setup_id,
                symbol=symbol,
                direction=direction,
                entry_low=entry_low,
                entry_high=entry_high,
                stop_loss=sl,
                target_1=tp1,
                target_2=tp2,
                target_3=tp3,
                detected_at=now,
                detected_price=current_price,
                strength=strength,
                reason=reason,
                source=source,
                status="active",
                price_path=[current_price],
            )
            self.setups[setup_id] = tracked
            new_ids.append(setup_id)

        # Nettoyer les vieux setups
        self._prune()

        # Sauvegarder
        if self.storage_path:
            self._save()

        if new_ids:
            logger.info("📊 %d nouveaux setups traqués (%s)", len(new_ids), symbol)
        return new_ids

    def _is_duplicate(self, new_setup: Any, current_price: float) -> bool:
        """Vérifie si un setup similaire existe déjà (actif et récent)."""
        direction = getattr(new_setup, 'direction', 'long')
        if direction == 'buy':
            direction = 'long'
        elif direction == 'sell':
            direction = 'short'

        for setup in self.setups.values():
            if setup.status != "active":
                continue
            if setup.direction != direction:
                continue
            # Même direction et prix d'entrée proche (< 1% d'écart) = doublon
        # Calculer le prix d'entrée moyen selon le type de setup
        if hasattr(new_setup, 'entry_mid'):
            entry_new = new_setup.entry_mid
        elif hasattr(new_setup, 'entry_zone_low'):
            entry_new = (new_setup.entry_zone_low + new_setup.entry_zone_high) / 2
        else:
            entry_new = current_price
            if abs(setup.entry_mid - entry_new) / max(setup.entry_mid, 1) < 0.01:
                detected_at = datetime.fromisoformat(setup.detected_at) if setup.detected_at else datetime.now()
                if (datetime.now() - detected_at).total_seconds() < 3600:  # Moins d'1h
                    return True
        return False

    def check_all(self, current_price: float, current_high: float, current_low: float) -> Dict[str, int]:
        """
        Vérifie tous les setups actifs contre le prix actuel.
        Met à jour les statuts si TP ou SL touché.
        Retourne le compte des changements.
        """
        changes = {"tp1": 0, "tp2": 0, "tp3": 0, "sl": 0, "expired": 0}
        now = datetime.now()

        for setup in list(self.setups.values()):
            # Ajouter le prix au chemin
            if len(setup.price_path) < 200:
                setup.price_path.append(current_price)

            if setup.status != "active":
                continue

            # Vérifier expiration
            detected_at = datetime.fromisoformat(setup.detected_at) if setup.detected_at else now
            hours_elapsed = (now - detected_at).total_seconds() / 3600
            if hours_elapsed > self._expiry_hours:
                setup.status = "expired"
                setup.outcome_at = now.isoformat()
                changes["expired"] += 1
                continue

            # Vérifier TP/SL
            outcome = setup.check_outcome(current_price, current_high, current_low)
            if outcome:
                if outcome.startswith("tp"):
                    setup.status = f"win_{outcome}"
                else:
                    setup.status = "loss"
                setup.outcome_price = current_price
                setup.outcome_at = now.isoformat()
                setup.bars_to_outcome = len(setup.price_path)
                changes[outcome] += 1

        if sum(changes.values()) > 0:
            logger.info("📊 Setup outcomes: %s", changes)
            if self.storage_path:
                self._save()

        return changes

    def get_active(self) -> List[TrackedSetup]:
        """Retourne les setups actifs, triés par date de détection (récent d'abord)."""
        active = [s for s in self.setups.values() if s.status == "active"]
        active.sort(key=lambda s: s.detected_at, reverse=True)
        return active

    def get_completed(self, limit: int = 50) -> List[TrackedSetup]:
        """Retourne les setups terminés (win ou loss)."""
        completed = [s for s in self.setups.values() if s.status in ("win_tp1", "win_tp2", "win_tp3", "loss")]
        completed.sort(key=lambda s: s.outcome_at or s.detected_at, reverse=True)
        return completed[:limit]

    def get_stats(self) -> Dict:
        """Statistiques globales des setups traqués."""
        completed = [s for s in self.setups.values()
                     if s.status in ("win_tp1", "win_tp2", "win_tp3", "loss")]
        active = self.get_active()
        total = len(completed) + len(active)

        wins = [s for s in completed if s.status.startswith("win_")]
        losses = [s for s in completed if s.status == "loss"]

        win_count = len(wins)
        loss_count = len(losses)
        total_closed = win_count + loss_count

        win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0

        # Avg R:R réalisé (pour les setups gagnants)
        avg_rr_realized = 0.0
        if wins:
            total_rr = 0.0
            count_rr = 0
            for w in wins:
                rr = w.risk_reward()
                if rr > 0:
                    total_rr += rr
                    count_rr += 1
            avg_rr_realized = total_rr / count_rr if count_rr > 0 else 0.0

        # Best / Worst
        best_setup = None
        worst_setup = None
        if wins:
            best_setup = max(wins, key=lambda s: s.strength)
        if losses:
            worst_setup = max(losses, key=lambda s: s.strength)

        # Par source
        by_source = {}
        for s in completed:
            src = s.source or "unknown"
            if src not in by_source:
                by_source[src] = {"wins": 0, "losses": 0}
            if s.status.startswith("win_"):
                by_source[src]["wins"] += 1
            else:
                by_source[src]["losses"] += 1

        # Par direction
        long_wins = len([s for s in wins if s.direction == "long"])
        long_losses = len([s for s in losses if s.direction == "long"])
        short_wins = len([s for s in wins if s.direction == "short"])
        short_losses = len([s for s in losses if s.direction == "short"])

        # Temps moyen avant outcome (en barres)
        avg_bars = 0.0
        bars_list = [s.bars_to_outcome for s in completed if s.bars_to_outcome > 0]
        if bars_list:
            avg_bars = sum(bars_list) / len(bars_list)

        return {
            "total_tracked": total,
            "active": len(active),
            "completed": total_closed,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": round(win_rate, 1),
            "avg_rr_realized": round(avg_rr_realized, 2),
            "avg_bars_to_outcome": round(avg_bars, 1),
            "long": {"wins": long_wins, "losses": long_losses},
            "short": {"wins": short_wins, "losses": short_losses},
            "by_source": by_source,
            "best_strength": best_setup.strength if best_setup else 0,
            "worst_strength": worst_setup.strength if worst_setup else 0,
        }

    def get_recent_activity(self, hours: float = 24) -> Dict:
        """Activité récente (setups créés, outcomes) sur les dernières heures."""
        now = datetime.now()
        recent_created = 0
        recent_outcomes = 0
        recent_wins = 0

        for s in self.setups.values():
            detected_at = datetime.fromisoformat(s.detected_at) if s.detected_at else now
            if (now - detected_at).total_seconds() / 3600 <= hours:
                recent_created += 1
                if s.status.startswith("win_"):
                    recent_outcomes += 1
                    recent_wins += 1
                elif s.status == "loss":
                    recent_outcomes += 1

        return {
            "period_hours": hours,
            "setups_created": recent_created,
            "outcomes": recent_outcomes,
            "wins": recent_wins,
            "losses": recent_outcomes - recent_wins,
        }

    def _prune(self):
        """Supprime les vieux setups pour limiter la mémoire."""
        if len(self.setups) <= self._max_setups:
            return
        # Garder les plus récents
        sorted_ids = sorted(
            self.setups.keys(),
            key=lambda sid: self.setups[sid].detected_at,
            reverse=True,
        )
        for sid in sorted_ids[self._max_setups:]:
            del self.setups[sid]

    def _save(self):
        """Sauvegarde en JSON."""
        if not self.storage_path:
            return
        try:
            data = {}
            for sid, setup in self.setups.items():
                d = asdict(setup)
                d["price_path"] = d["price_path"][-50:]  # Garder max 50 points
                data[sid] = d
            os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Impossible de sauvegarder le tracker: %s", e)

    def _load(self):
        """Charge depuis JSON."""
        if not self.storage_path or not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sid, d in data.items():
                d["price_path"] = d.get("price_path", [])
                self.setups[sid] = TrackedSetup(**d)
            logger.info("📊 Tracker chargé: %d setups depuis %s", len(self.setups), self.storage_path)
        except Exception as e:
            logger.warning("Impossible de charger le tracker: %s", e)
