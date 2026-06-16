"""
Suivi des setups de trading ICT.
Enregistre les setups détectés, vérifie la direction prise par le prix
par rapport aux TP/SL, et fournit des statistiques de performance.

Fonctionne en mémoire (session Streamlit) + persistance JSON optionnelle.
"""

import json
import logging
import math
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger("SetupTracker")


@dataclass
class TrackedSetup:
    """Un setup de trading suivi dans le temps avec contexte complet pour analyse prédictive."""
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
    # ─── Contexte de marché au moment de la détection ───
    killzone_active: str = ""        # "Asie", "Londres", "New York", "Silver Bullet NY"
    macro_bias: str = ""             # "bullish", "bearish", "neutral"
    price_zone: str = ""             # "discount", "premium", "equilibrium"
    pd_array_range: float = 0.0      # Range du PD Array (volatilité)
    killzone_conformity_score: float = 0.0  # 0-1
    nb_tfs_bullish: int = 0
    nb_tfs_bearish: int = 0
    nb_tfs_neutral: int = 0
    nb_tfs_total: int = 0
    day_of_week: int = 0             # 0=Lundi, 4=Vendredi, 6=Dimanche
    hour_of_day: int = 0             # 0-23
    sweep_present: bool = False      # Sweep récent sur key level ?
    proximity_concepts_json: str = ""  # JSON: {"OB":3, "FVG":2, "BSL":1, ...}

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
        self._max_active = 200           # Max setups actifs en mémoire
        self._max_completed = 10000      # Max setups terminés (historique)
        self._expiry_hours = 168         # Expiration après 7 jours
        if storage_path:
            self._load()

    def log_setups(
        self,
        setups: List[Any],  # List[ProximitySetup] ou List[TradeSignal]
        current_price: float,
        symbol: str = "XAUUSD",
        source: str = "proximity",
        context: Optional[Dict] = None,
    ) -> List[str]:
        """
        Enregistre de nouveaux setups pour suivi avec contexte de marché.
        Évite les doublons (même direction + prix proche + détection récente).
        
        Args:
            context: dict optionnel avec les clés:
                killzone_active, macro_bias, price_zone, pd_array_range,
                killzone_conformity_score, nb_tfs_bullish/bearish/neutral/total,
                day_of_week, hour_of_day, sweep_present, proximity_concepts
        Retourne les IDs créés.
        """
        new_ids = []
        now_dt = datetime.now()
        now = now_dt.isoformat()
        ctx = context or {}

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
                # Contexte de marché
                killzone_active=ctx.get("killzone_active", ""),
                macro_bias=ctx.get("macro_bias", ""),
                price_zone=ctx.get("price_zone", ""),
                pd_array_range=ctx.get("pd_array_range", 0.0),
                killzone_conformity_score=ctx.get("killzone_conformity_score", 0.0),
                nb_tfs_bullish=ctx.get("nb_tfs_bullish", 0),
                nb_tfs_bearish=ctx.get("nb_tfs_bearish", 0),
                nb_tfs_neutral=ctx.get("nb_tfs_neutral", 0),
                nb_tfs_total=ctx.get("nb_tfs_total", 0),
                day_of_week=ctx.get("day_of_week", now_dt.weekday()),
                hour_of_day=ctx.get("hour_of_day", now_dt.hour),
                sweep_present=ctx.get("sweep_present", False),
                proximity_concepts_json=ctx.get("proximity_concepts_json", ""),
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

    def find_similar_setups(
        self, current_context: Dict, direction: str, top_n: int = 5,
    ) -> List[Dict]:
        """
        Compare le contexte actuel aux setups gagnants passés et retourne
        les plus similaires avec leur score de similarité et outcome.
        
        Utilisé pour évaluer si le setup actuel ressemble à des setups
        historiquement gagnants (fort potentiel) ou perdants (risque élevé).
        
        Retourne une liste de dicts triés par similarité décroissante :
        [{setup_id, direction, outcome, win, similarity_score, match_details, ...}]
        """
        completed = [
            s for s in self.setups.values()
            if s.status.startswith("win_") or s.status == "loss"
        ]
        if not completed:
            return []

        # Construire le vecteur de features du contexte actuel
        target_vec = self._context_to_vector(current_context, direction)

        results = []
        for s in completed:
            hist_ctx = {
                "direction": s.direction,
                "killzone_active": s.killzone_active,
                "macro_bias": s.macro_bias,
                "price_zone": s.price_zone,
                "pd_array_range": s.pd_array_range,
                "killzone_conformity_score": s.killzone_conformity_score,
                "nb_tfs_bullish": s.nb_tfs_bullish,
                "nb_tfs_bearish": s.nb_tfs_bearish,
                "nb_tfs_neutral": s.nb_tfs_neutral,
                "day_of_week": s.day_of_week,
                "hour_of_day": s.hour_of_day,
                "sweep_present": s.sweep_present,
                "strength": s.strength,
                "source": s.source,
                "proximity_concepts_json": s.proximity_concepts_json,
            }
            hist_vec = self._context_to_vector(hist_ctx, s.direction)
            similarity = self._cosine_similarity(target_vec, hist_vec)

            # Bonus si même direction
            if s.direction == direction:
                similarity += 0.1
            # Bonus si même source
            if s.source == current_context.get("source", ""):
                similarity += 0.05

            results.append({
                "setup_id": s.id,
                "direction": s.direction,
                "outcome": s.status,
                "win": s.status.startswith("win_"),
                "similarity_score": round(min(similarity, 1.0), 3),
                "detected_at": s.detected_at,
                "entry_mid": s.entry_mid,
                "strength": s.strength,
                "killzone_active": s.killzone_active,
                "macro_bias": s.macro_bias,
                "source": s.source,
            })

        # Trier par similarité décroissante
        results.sort(key=lambda r: r["similarity_score"], reverse=True)
        return results[:top_n]

    def get_predictive_score(self, current_context: Dict, direction: str) -> Dict:
        """
        Score prédictif basé sur l'historique :
        - Cherche les 10 setups passés les plus similaires
        - Calcule le win rate et le R:R moyen de ces setups similaires
        - Compare au win rate global pour déterminer si le contexte est favorable
        
        Retourne un dict avec predictive_score (0-100), confidence, et détails.
        """
        similar = self.find_similar_setups(current_context, direction, top_n=10)
        if len(similar) < 3:
            return {
                "predictive_score": 50,
                "confidence": "low",
                "similar_count": len(similar),
                "similar_win_rate": 0,
                "similar_avg_rr": 0,
                "global_win_rate": 0,
                "verdict": "Pas assez d'historique similaire pour évaluer",
            }

        # Win rate des setups similaires
        similar_wins = sum(1 for s in similar if s["win"])
        similar_win_rate = similar_wins / len(similar) * 100

        # R:R moyen des setups similaires gagnants
        similar_rrs = []
        for s in similar:
            if s["win"]:
                setup = self.setups.get(s["setup_id"])
                if setup:
                    rr = setup.risk_reward()
                    if rr > 0:
                        similar_rrs.append(rr)
        similar_avg_rr = sum(similar_rrs) / len(similar_rrs) if similar_rrs else 0

        # Win rate global
        stats = self.get_stats()
        global_win_rate = stats.get("win_rate", 0)
        global_avg_rr = stats.get("avg_rr_realized", 0)

        # Score prédictif : combinaison du win rate similaire vs global et R:R
        wr_bonus = (similar_win_rate - global_win_rate) / 2  # ±50 max
        rr_bonus = (similar_avg_rr - global_avg_rr) * 10 if global_avg_rr > 0 else 0  # ±30 max
        base_score = 50
        predictive_score = max(0, min(100, base_score + wr_bonus + rr_bonus))

        # Confiance basée sur le nombre d'échantillons similaires
        if len(similar) >= 8:
            confidence = "high"
        elif len(similar) >= 5:
            confidence = "medium"
        else:
            confidence = "low"

        # Verdict
        if predictive_score >= 65:
            verdict = "✅ Contexte favorable — setups similaires gagnants dans le passé"
        elif predictive_score >= 45:
            verdict = "⚠️ Contexte neutre — résultats mitigés dans des conditions similaires"
        else:
            verdict = "❌ Contexte défavorable — setups similaires souvent perdants"

        return {
            "predictive_score": round(predictive_score, 1),
            "confidence": confidence,
            "similar_count": len(similar),
            "similar_win_rate": round(similar_win_rate, 1),
            "similar_avg_rr": round(similar_avg_rr, 2),
            "global_win_rate": round(global_win_rate, 1),
            "global_avg_rr": round(global_avg_rr, 2),
            "verdict": verdict,
            "top_similar": similar[:3],
        }

    @staticmethod
    def _context_to_vector(ctx: Dict, direction: str) -> List[float]:
        """Convertit un contexte en vecteur de features numériques pour comparaison."""
        vec = []

        # Killzone active (one-hot: asia, london, ny, silver_bullet)
        kz = ctx.get("killzone_active", "")
        vec.append(1.0 if "Asie" in kz else 0.0)
        vec.append(1.0 if "Londres" in kz else 0.0)
        vec.append(1.0 if ("New York" in kz and "Silver" not in kz) else 0.0)
        vec.append(1.0 if "Silver" in kz else 0.0)

        # Macro bias (one-hot: bullish, bearish, neutral)
        mb = ctx.get("macro_bias", "")
        vec.append(1.0 if mb == "bullish" else 0.0)
        vec.append(1.0 if mb == "bearish" else 0.0)
        vec.append(1.0 if mb == "neutral" else 0.0)

        # Price zone (one-hot: discount, premium, equilibrium)
        pz = ctx.get("price_zone", "")
        vec.append(1.0 if pz == "discount" else 0.0)
        vec.append(1.0 if pz == "premium" else 0.0)
        vec.append(1.0 if pz == "equilibrium" else 0.0)

        # Direction (one-hot: long, short)
        vec.append(1.0 if direction == "long" else 0.0)
        vec.append(1.0 if direction == "short" else 0.0)

        # Source (one-hot: signal, proximity, sweep, keylevel)
        src = ctx.get("source", "")
        vec.append(1.0 if src == "signal" else 0.0)
        vec.append(1.0 if src == "proximity" else 0.0)
        vec.append(1.0 if src == "sweep" else 0.0)
        vec.append(1.0 if src == "keylevel" else 0.0)

        # Sweep present
        vec.append(1.0 if ctx.get("sweep_present") else 0.0)

        # Day of week (normalisé 0-1, cyclique: cos/sin encoding)
        dow = ctx.get("day_of_week", 0)
        vec.append(math.cos(2 * math.pi * dow / 7))
        vec.append(math.sin(2 * math.pi * dow / 7))

        # Hour of day (normalisé 0-1, cyclique)
        hod = ctx.get("hour_of_day", 12)
        vec.append(math.cos(2 * math.pi * hod / 24))
        vec.append(math.sin(2 * math.pi * hod / 24))

        # Features numériques normalisés
        pd_range = ctx.get("pd_array_range", 50)
        vec.append(min(pd_range / 200.0, 1.0))  # PD range normalisé

        kz_conf = ctx.get("killzone_conformity_score", 0)
        vec.append(kz_conf)  # Déjà entre 0 et 1

        strength = ctx.get("strength", 0.5)
        vec.append(strength)  # Déjà entre 0 et 1

        # TF alignment (normalisé)
        nb_total = ctx.get("nb_tfs_total", 8)
        if nb_total > 0:
            vec.append(ctx.get("nb_tfs_bullish", 0) / nb_total)
            vec.append(ctx.get("nb_tfs_bearish", 0) / nb_total)
            vec.append(ctx.get("nb_tfs_neutral", 0) / nb_total)
        else:
            vec.extend([0, 0, 0])

        # Concepts de proximité (si JSON présent, compter les types)
        concepts_json = ctx.get("proximity_concepts_json", "")
        concept_types = ["OB", "FVG", "OTE", "BSL", "SSL", "MSS", "GAP", "Discount", "Premium"]
        concept_counts = {}
        if concepts_json:
            try:
                concept_counts = json.loads(concepts_json)
            except Exception:
                pass
        for ct in concept_types:
            vec.append(min(concept_counts.get(ct, 0) / 5.0, 1.0))

        return vec

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Calcule la similarité cosinus entre deux vecteurs."""
        if len(a) != len(b) or len(a) == 0:
            return 0.0
        dot = sum(ai * bi for ai, bi in zip(a, b))
        norm_a = math.sqrt(sum(ai * ai for ai in a))
        norm_b = math.sqrt(sum(bi * bi for bi in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

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
        """Nettoie les vieux setups actifs expirés. Ne supprime JAMAIS les setups terminés (historique)."""
        # 1. Supprimer les setups actifs expirés
        now = datetime.now()
        expired_ids = []
        for sid, s in self.setups.items():
            if s.status == "active":
                try:
                    detected_at = datetime.fromisoformat(s.detected_at) if s.detected_at else now
                except Exception:
                    detected_at = now
                hours_elapsed = (now - detected_at).total_seconds() / 3600
                if hours_elapsed > self._expiry_hours:
                    expired_ids.append(sid)
        for sid in expired_ids:
            del self.setups[sid]

        # 2. Si encore trop d'actifs, supprimer les plus anciens (mais jamais les terminés)
        active = [s for s in self.setups.values() if s.status == "active"]
        if len(active) > self._max_active:
            active.sort(key=lambda s: s.detected_at)
            for s in active[:len(active) - self._max_active]:
                del self.setups[s.id]

        # 3. Si trop de terminés, supprimer les plus anciens (historique long terme préservé)
        completed = [s for s in self.setups.values() if s.status.startswith("win_") or s.status == "loss"]
        if len(completed) > self._max_completed:
            completed.sort(key=lambda s: s.outcome_at or s.detected_at)
            for s in completed[:len(completed) - self._max_completed]:
                del self.setups[s.id]

        if expired_ids:
            logger.info("🧹 %d setups actifs expirés supprimés", len(expired_ids))

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
