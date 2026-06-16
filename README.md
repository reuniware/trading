# 🏦 ICT Trading System — Multi-Timeframe Analyzer (FTMO MT5)

Système de trading algorithmique basé sur la méthodologie **Inner Circle Trader (ICT)**.  
Connecté à **MetaTrader 5** (compte FTMO) pour l'analyse multi-timeframes, la détection de concepts ICT, et la génération de signaux de trading.

---

## 📋 Table des matières

- [Architecture](#-architecture-du-projet)
- [Fonctionnalités](#-fonctionnalités)
- [Démarrage rapide](#-dmarrage-rapide)
- [Utilisation](#-utilisation)
- [Modules](#-modules)
- [Concepts ICT détectés](#-concepts-ict-détectés)
- [Résultats de performance](#-résultats-de-performance)
- [Dépannage](#-dpannage)
- [Dépendances](#-dépendances)
- [Licence](#-licence)

---

## 🏗️ Architecture du projet

```
trading/
├── main.py                          # Point d'entrée CLI (dashboard, scan, analyze...)
├── start_dashboard.bat              # Lanceur Windows avec cleanup auto
├── requirements.txt                 # Dépendances Python
├── README.md                        # Documentation
├── src/
│   ├── __init__.py
│   ├── config.py                    # Configuration centralisée
│   ├── mt5_connector.py             # Connexion singleton MT5
│   ├── data_engine.py               # Données OHLC multi-TF avec cache
│   ├── ict_concepts.py              # Détection OB, FVG, MSS, Liquidité, Key Levels, Sweeps
│   ├── sessions.py                  # Kill Zones + Conformité prix/killzone
│   ├── proximity.py                 # Proximité prix + setups trading LONG/SHORT
│   ├── signal_generator.py          # Scoring et génération de signaux
│   ├── setup_tracker.py             # Suivi des setups (TP/SL, win rate, persistance JSON)
│   ├── trade_manager.py             # Exécution d'ordres MT5
│   ├── risk_manager.py              # Position sizing et limites
│   ├── account_monitor.py           # Stats compte et historique
│   ├── analyzer.py                  # Rapport d'analyse complet
│   └── dashboard.py                 # Interface Streamlit temps réel
├── screenshots_tradingview/
│   └── analyse_ICT_XAUUSD_20260615.md   # Analyse de référence TradingView
└── analyse_ICT_XAUUSD_*.md          # Rapports générés automatiquement
```

---

## ✨ Fonctionnalités

### 📊 Analyse Multi-Timeframes (8 timeframes)
| Timeframe | Échelle | Usage |
|-----------|---------|-------|
| **MN1** | Mensuel | Vision macro / tendance long terme |
| **W1** | Hebdo | Structure moyen terme |
| **D1** | Daily | Bias quotidien |
| **H4** | 4 heures | Cadre opérationnel MT |
| **H1** | 1 heure | Point d'entrée CT |
| **M15** | 15 minutes | Exécution |
| **M5** | 5 minutes | Micro-exécution |
| **M1** | 1 minute | Scalping |

### 🔍 Concepts ICT détectés
- **Order Blocks (OB)** — Dernière bougie avant impulsion
- **Fair Value Gaps (FVG)** — Gaps de prix à 3 bougies
- **Market Structure Shift (MSS/BOS)** — Cassures de structure
- **Buy-Side / Sell-Side Liquidity (BSL/SSL)** — Zones de liquidité
- **Key Levels (PDH/PDL/PWH/PWL/PMH/PML)** — Niveaux clés jour/semaine/mois précédents
- **Liquidity Sweeps (Judas Swing / Turtle Soup)** — Chasses de liquidité sur niveaux clés
- **Discount / Premium Zones** — Zones d'achat/vente ICT

### 🎯 Scoring des signaux (0-100)
- **Bias alignment** : Cohérence multi-TF (max +50 pts)
- **Concepts strength** : Force des OB/FVG/MSS par TF (max +30 pts)
- **Sweep bonus** : +12 pts si sweep favorable, −5 pts si opposé
- **Liquidity confluence** : Bonus pour plusieurs BSL/SSL proches
- **Kill Zones bonus** : Session active / Silver Bullet (max +12 pts)
- **Conflit TF malus** : Détection de conflits directionnels (−10 pts)
- **Normalisation** : Score final entre 0 et 100

### 🗂️ Suivi des Setups (Setup Tracker)
- **Tracking automatique** — chaque setup détecté est loggé avec entrée/SL/TP
- **Vérification continue** — TP1/TP2/TP3 touché ou SL = résultat enregistré
- **Stats en direct** — Win rate, R:R moyen, par direction LONG/SHORT, par source (signal/proximity)
- **Progrès vers TP** — affichage du % de progression par setup actif
- **Persistance JSON** — les setups survivent aux redémarrages

### 🔫 Conformité Killzone
- **Vérification du comportement du prix** — le prix fait-il ce qu'il est censé faire dans la killzone ?
- **Asie** → range étroit, consolidation, faible volume
- **Londres** → trend directionnel, forte volatilité
- **New York** → sweeps de liquidité, potentiel reversal
- **Silver Bullet** → impulsion forte, expansion range
- **Score de conformité 0-100%** avec badge ✅/⚠️/❌

### 🔄 Auto-Redémarrage intelligent
- **Survie aux erreurs de code transitoires** — si le dashboard crash après une modification live
- **Message d'erreur affiché** + explication + traceback
- **Redémarrage automatique** en 3 secondes (cleanup caches + kill PID + restart)
- **Anti-boucle** — max 3 redémarrages en 60s, puis arrêt définitif avec message

### 🎯 Scoring des signaux (0-100)
- **Bias alignment** : Cohérence multi-TF (max +50 pts)
- **Concepts strength** : Force des OB/FVG/MSS par TF (max +30 pts)
- **Kill Zones bonus** : Session active / Silver Bullet (max +12 pts)
- **Conflit TF malus** : Détection de conflits directionnels (−10 pts)
- **Normalisation** : Score final entre 0 et 100

### 📈 Dashboard temps réel (Streamlit)
- Graphique bougies avec OB/FVG superposés
- Prix Bid/Ask en direct
- Signaux LONG/SHORT avec TP Fibonacci (1.272/1.414/1.618)
- Positions ouvertes avec gestion
- Performance 30 jours + Totale
- Courbe d'equity
- Matrice des biases multi-TF
- **⏱️ Timeframes sélectionnables** : cases à cocher dans la sidebar pour filtrer les TFs analysés
- **🕐 Sessions et Silver Bullet** : badges avec décomptes ouverture/fermeture, animation pulse orange
- **📊 Bannière Macro ICT** : contexte global (Haussière/Baissière/Neutre) + zone de prix + killzone active + conformité killzone
- **📍 Proximité ICT** : tableau DataFrame structuré (Concept, TF, Direction, Zone, Distance, Force)
- **🎯 Setups de trading** : tableau DataFrame complet (Direction, Force, R:R, TFs, Entrée, SL, TP1-3, Raisons)
- **📊 Suivi des Setups** : stats globales (win rate, R:R), par direction, par source, progrès TP en temps réel
- **🔫 Conformité Killzone** : comportement attendu vs observé, score, alertes
- **📖 Guide ICT intégré** : expandeur avec explications des killzones et macro, **toutes** les killzones actives surlignées

---

## 🚀 Démarrage rapide

### 1. Prérequis
- **Python 3.10+** installé
- **MetaTrader 5 OUVERT et connecté** au compte FTMO — le terminal doit être lancé **avant** toute commande
- Compte FTMO démo ou réel

### 2. Installation

```bash
pip install -r requirements.txt
```

### 3. Configuration
Éditez `src/config.py` pour ajuster :
- `SYMBOLS` — Symboles à trader (défaut : `XAUUSD`)
- `RISK` — Paramètres de risque (max risk %, max positions, R:R)
- `ICT` — Paramètres de détection ICT (lookback, ratios)

Le chemin du terminal MT5 est configurable dans `src/mt5_connector.py` :
```python
self.terminal_path = r"C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe"
```
> ⚠️ Si vous utilisez un autre broker que FTMO, modifiez ce chemin.

### 4. Lancer le système

```bash
# Étape 1 : Vérifier que MT5 est ouvert et connecté

# Étape 2 : Scanner les signaux (one-shot, quitte après affichage)
python main.py scan --symbol XAUUSD

# Étape 3 : Lancer le dashboard (processus continu — ouvrez un terminal dédié)
python main.py dashboard
# Puis ouvrez http://localhost:8501 dans votre navigateur
```

> 💡 **Windows :** le plus simple est de double-cliquer sur `start_dashboard.bat` depuis l'Explorateur.
> Il nettoie automatiquement les processus bloquants et les caches avant de lancer le dashboard.
>
> 💡 **Git Bash :** lancez le dashboard avec `python main.py dashboard &` pour le mettre en arrière-plan.
> Sinon le terminal reste bloqué (c'est normal, Streamlit tourne en continu).

---

## 🎮 Utilisation

### Commandes CLI

| Commande | Description | Type |
|----------|-------------|------|
| `python main.py scan --symbol XAUUSD` | Scanner ICT complet (bias, signaux, proximité, setups) | One-shot |
| `python main.py scan -t D1,H4,H1,M15` | Scanner avec timeframes filtrés | One-shot |
| `python main.py analyze --symbol XAUUSD` | Générer un rapport `.md` complet | One-shot |
| `python main.py dashboard` | Lancer le dashboard Streamlit | **Continu** 🔄 |
| `python main.py positions` | Afficher les positions ouvertes | One-shot |
| `python main.py account` | Infos compte (balance, equity, P&L) | One-shot |

> 🔄 **Continu** = le processus ne s'arrête pas tout seul. Utilisez un terminal dédié ou `start_dashboard.bat`.

### Dashboard Streamlit

```bash
# Méthode recommandée — cleanup automatique (PID + caches) puis lancement
python main.py dashboard

# Alternative Windows : double-clic sur start_dashboard.bat

# ⚠️ Déconseillé — pas de cleanup automatique
streamlit run src/dashboard.py
```

Après le lancement, accédez au dashboard : **[http://localhost:8501](http://localhost:8501)**

> ⚠️ **Après une mise à jour du code**, utilisez `python main.py dashboard` ou `start_dashboard.bat`.
> Le lancement direct via `streamlit run` ne nettoie pas les caches `.pyc` et peut causer des `AttributeError`.

---

## 🧹 Cleanup automatique (PID + cache)

À chaque lancement via `python main.py dashboard` ou `start_dashboard.bat`, le système :

1. **Tue les anciens processus Streamlit** sur le port `8501` via `netstat` + `taskkill`
2. **Supprime tous les `__pycache__`** du projet (`.git` et `.venv` exclus)
3. **Supprime les fichiers `.pyc` orphelins**
4. Lance Streamlit avec l'option `-B` (désactive la génération de bytecode)

Ce mécanisme prévient les `AttributeError` causées par un cache obsolète après une modification du code source.

---

## 📦 Modules

### `src/config.py`
Configuration centralisée : symboles, timeframes, paramètres de risque, paramètres ICT, sessions.

### `src/mt5_connector.py`
Singleton de connexion à MetaTrader 5 avec auto-reconnect et logging.

### `src/data_engine.py`
Moteur de données multi-TF avec cache TTL configurable. Récupère les données OHLC de MT5.

### `src/ict_concepts.py`
Cœur du système — détection de tous les concepts ICT :
- `OrderBlock` : bullish/bearish avec force
- `FairValueGap` : gap distance et force
- `MarketStructureShift` : MSS/BOS avec direction
- `LiquidityLevel` : BSL/SSL avec sweep detection
- `KeyLevel` : PDH/PDL (jour), PWH/PWL (semaine), PMH/PML (mois) — aimants à liquidité
- `SweepSignal` : détection de Judas Swing / Turtle Soup sur niveaux clés
- `DiscountPremium` : zones d'équilibre
- **Filtrage par prix** : OB/FVG/MSS > 35% du prix actuel ignorés (évite les artefacts historiques)

### `src/sessions.py`
Détection des sessions de trading + conformité killzone :
- Session Asiatique (22:00-08:00 UTC)
- Session Londres (07:00-16:00 UTC)
- Session New York (13:00-21:00 UTC)
- Silver Bullet (13:30-15:00 UTC)
- **`KillzoneConformity`** : vérifie si le comportement du prix correspond aux attentes de la killzone active
  - Score adaptatif basé sur le PD Array range (range%, volatilité, volume, sweeps)
  - Alerte si comportement anormal

### `src/signal_generator.py`
Génération de signaux avec scoring ICT pur :
- Confluence multi-TF pondérée par hiérarchie
- Zone d'entrée = OB/FVG le plus proche du prix
- SL sous l'OB / au-dessus du FVG
- TP Fibonacci 1.272 / 1.414 / 1.618

### `src/trade_manager.py`
Exécution d'ordres MT5 :
- Ordres market/pending
- Modification SL/TP
- Fermeture de positions
- Placement basé sur les signaux ICT

### `src/risk_manager.py`
Gestion des risques :
- Position sizing (fixed_risk / fixed_lot)
- Daily loss limit
- Max open positions
- Validation R:R minimum

### `src/account_monitor.py`
Monitoring du compte :
- Stats en temps réel (balance, equity, margin)
- Historique des trades (30 jours / total)
- Win rate, profit factor, courbe d'equity
- Filtre des opérations non-trade (type BALANCE)

### `src/proximity.py`
Analyse de proximité du prix avec les concepts ICT :
- Détection des OB, FVG, OTE, Discount/Premium, BSL/SSL, MSS proches du prix
- **Key Levels** : PDH/PDL/PWH/PWL comme alertes de proximité
- **Sweep alerts** : signaux de sweep intégrés comme alertes prioritaires
- Filtre adaptatif basé sur le PD Array range
- Génération de **setups LONG/SHORT** avec SL et TP
  - **Sweep setups** : entrées basées sur les sweeps de niveaux clés (prioritaires)
  - **Key level setups** : entrées basées sur la proximité BSL/SSL
- R:R calculé automatiquement
- **Raisons détaillées** : pourquoi l'entrée, pourquoi le SL à ce niveau, pourquoi le TP

### `src/analyzer.py`
Analyseur complet :
- Génération de rapports markdown structurés
- Matrice des biases multi-TF
- Détection de conflits directionnels
- Résumé top-down ICT
- Intégration des key levels, sweeps, killzone conformity dans les rapports
- Intégration du setup tracker (log auto + vérification TP/SL)

### `src/dashboard.py`
Interface Streamlit temps réel :
- Thème dark professionnel
- Graphiques Plotly avec concepts ICT
- Auto-refresh configurable
- Cards métriques responsives
- **📍 Proximité ICT** avec détails par concept
- **🎯 Setups de trading** avec raisons entrée/SL/TP
- **📊 Suivi des Setups** avec stats, progrès TP, par direction/source
- **🔫 Conformité Killzone** avec comportement attendu vs observé
- **🔄 Auto-redémarrage** intelligent en cas d'erreur transitoire (anti-boucle 3/60s)

### `src/setup_tracker.py`
Suivi des setups de trading :
- **`TrackedSetup`** : ID unique, direction, entrée/SL/TP, statut, chemin de prix
- **`SetupTracker`** : log, vérification continue TP/SL, stats, persistance JSON
- Détection auto des outcomes : TP1/TP2/TP3 → WIN, SL touché → LOSS
- Anti-doublons (même direction + prix proche + <1h)
- Stats : win rate, R:R moyen, par direction, par source

---

## 🧠 Concepts ICT détectés

### Order Block (OB)
> Dernière bougie baissière avant une forte impulsion haussière (bullish OB)  
> Dernière bougie haussière avant une forte impulsion baissière (bearish OB)

**Algorithme :**
1. Bougie d'impulsion : corps > 1.5× corps précédent
2. Bougie précédente : corps > 20% du range
3. Force : ratio d'impulsion normalisé (0.0 - 1.0)

### Fair Value Gap (FVG)
> Gap entre 3 bougies consécutives créant un déséquilibre de prix

**Bullish FVG** : `low[i+1] > high[i-1]` (gap haussier)  
**Bearish FVG** : `high[i+1] < low[i-1]` (gap baissier)

### Market Structure Shift (MSS)
> Cassure d'un swing high (bullish) ou swing low (bearish) avec momentum

**BOS** : Simple break of structure  
**MSS** : Break avec confirmation HH/HL ou LH/LL

### Liquidité (BSL/SSL)
- **BSL** : Buy-Side Liquidity (au-dessus des swing highs)
- **SSL** : Sell-Side Liquidity (en-dessous des swing lows)
- **Sweep** : Détection de chasse de liquidité (wick)

---

## 🩺 Dépannage

| Problème | Solution |
|----------|----------|
| `[FAIL] Impossible de se connecter a MT5` | **Ouvrez d'abord le terminal MT5** et connectez-vous au compte. Le système ne lance pas MT5 automatiquement. |
| `Port 8501 already in use` | Lancez via `python main.py dashboard` ou `start_dashboard.bat` — le cleanup automatique tuera l'ancien processus. |
| `AttributeError` / `UnboundLocalError` après modification du code | Le dashboard détecte l'erreur et **redémarre automatiquement** en 3s (cleanup + restart). Après 3 erreurs en 60s, il s'arrête et affiche les instructions de redémarrage manuel. |
| Dashboard ne se lance pas sous Git Bash | Le processus `python main.py dashboard` est bloquant. Ajoutez `&` à la fin (`python main.py dashboard &`) ou ouvrez un second terminal. |
| Chemin MT5 incorrect | Modifiez `self.terminal_path` dans `src/mt5_connector.py` avec le chemin de votre terminal. |

## 📊 Résultats de performance

Compte FTMO (€10k) — Données réelles au 15 Juin 2026 :

| Métrique | 30 jours | Total |
|----------|----------|-------|
| **Trades** | 153 | 154 |
| **Win Rate** | 30.9% | 31.2% |
| **P&L Net** | +€885.35 | **+€935.65** |
| **Profit Factor** | 1.81 | 1.86 |
| **Avg Profit** | €5.82 | €6.08 |
| **Max Gain** | +€455.36 | +€455.36 |
| **Max Loss** | -€196.31 | -€196.31 |

> 💡 Win rate bas (~31%) mais profit factor > 1.8 — les trades gagnants sont en moyenne 4× plus grands que les perdants. C'est le profil typique d'une stratégie ICT.

---

## 📦 Dépendances

```
MetaTrader5>=5.0.5735    # API MT5 Python
pandas>=2.0.0             # Manipulation de données
numpy>=1.24.0             # Calculs numériques
streamlit>=1.30.0         # Dashboard temps réel
plotly>=5.18.0            # Graphiques interactifs
```

---

## ⚠️ Disclaimer

> **⚠️ IMPORTANT :** Ce logiciel est fourni à titre éducatif et informatif uniquement.  
> Il ne constitue **pas un conseil en investissement**.  
> Le trading comporte des risques financiers importants — vous pouvez perdre tout ou partie de votre capital.  
> Effectuez toujours vos propres recherches (DYOR) et ne risquez jamais plus que ce que vous pouvez accepter de perdre.  
> Les concepts ICT (Inner Circle Trader) sont une méthodologie d'analyse technique et non une garantie de résultats.

---

*Généré par Codebuff AI — Juin 2026*
