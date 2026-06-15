# 🏦 ICT Trading System — Multi-Timeframe Analyzer (FTMO MT5)

Système de trading algorithmique basé sur la méthodologie **Inner Circle Trader (ICT)**.  
Connecté à **MetaTrader 5** (compte FTMO) pour l'analyse multi-timeframes, la détection de concepts ICT, et la génération de signaux de trading.

---

## 📋 Table des matières

- [Architecture](#-architecture-du-projet)
- [Fonctionnalités](#-fonctionnalités)
- [Installation](#-installation)
- [Utilisation](#-utilisation)
- [Modules](#-modules)
- [Concepts ICT détectés](#-concepts-ict-détectés)
- [Résultats de performance](#-résultats-de-performance)
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
│   ├── ict_concepts.py              # Détection OB, FVG, MSS, Liquidité, PriceGap
│   ├── sessions.py                  # Kill Zones (Asie/Londres/NY)
│   ├── proximity.py                 # Proximité prix + setups trading LONG/SHORT
│   ├── signal_generator.py          # Scoring et génération de signaux
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
- **Liquidity Sweeps** — Chasses de liquidité détectées
- **Discount / Premium Zones** — Zones d'achat/vente ICT

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
- **🕐 Sessions et Silver Bullet** : badges avec décomptes ouverture/fermeture
- **📊 Bannière Macro ICT** : contexte global (Haussière/Baissière/Neutre) + zone de prix + killzone active + décompte
- **📍 Proximité ICT** : tableau DataFrame structuré (Concept, TF, Direction, Zone, Distance, Force)
- **🎯 Setups de trading** : tableau DataFrame complet (Direction, Force, R:R, TFs, Entrée, SL, TP1-3, Raisons)
- **📖 Guide ICT intégré** : expandeur avec explications des killzones et macro, mise en évidence dynamique de la session active

---

## 🚀 Installation

### Prérequis
- Python 3.10+
- MetaTrader 5 (FTMO Global Markets Terminal)
- Compte FTMO démo ou réel

### Installation des dépendances

```bash
pip install -r requirements.txt
```

### Configuration
Éditez `src/config.py` pour ajuster :
- `SYMBOLS` — Symboles à trader
- `RISK` — Paramètres de risque (max risk %, max positions, R:R)
- `ICT` — Paramètres de détection ICT (lookback, ratios)

Le path du terminal MT5 est configurable dans `src/mt5_connector.py` :
```python
self.terminal_path = r"C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe"
```

---

## 🎮 Utilisation

### CLI (Console)

```bash
# Dashboard Streamlit (par défaut)
python main.py

# Scanner les signaux ICT en temps réel
python main.py scan --symbol XAUUSD

# Générer un rapport d'analyse complet (.md)
python main.py analyze --symbol XAUUSD

# Afficher les positions ouvertes
python main.py positions

# Informations du compte
python main.py account
```

### Dashboard Streamlit (recommandé)

```bash
# Via main.py — NETTOIE les caches + tue les anciens processus automatiquement
python main.py
# ou explicitement :
python main.py dashboard
```

### Dashboard Streamlit (direct, sans cleanup)
```bash
# Lancement direct — PAS de nettoyage automatique
streamlit run src/dashboard.py
```

> ⚠️ **Important :** `streamlit run` ne nettoie pas les caches `.pyc`. Après une mise à jour du code, utilisez `python main.py dashboard` ou `start_dashboard.bat` pour éviter les erreurs `AttributeError` liées à un cache obsolète.

### Lanceur Windows (`start_dashboard.bat`)
```bat
# Double-clic sur start_dashboard.bat dans l'Explorateur
# Effectue le cleanup (PID + cache) puis lance le dashboard
```

Accès : [http://localhost:8501](http://localhost:8501)

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
- `DiscountPremium` : zones d'équilibre

### `src/sessions.py`
Détection des sessions de trading :
- Session Asiatique (22:00-08:00 UTC)
- Session Londres (07:00-16:00 UTC)
- Session New York (13:00-21:00 UTC)
- Silver Bullet (13:30-15:00 UTC)

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
- Filtre adaptatif basé sur le PD Array range
- Génération de **setups LONG/SHORT** avec SL et TP
- R:R calculé automatiquement
- **Raisons détaillées** : pourquoi l'entrée, pourquoi le SL à ce niveau, pourquoi le TP

### `src/analyzer.py`
Analyseur complet :
- Génération de rapports markdown structurés
- Matrice des biases multi-TF
- Détection de conflits directionnels
- Résumé top-down ICT
- Intégration des setups de trading dans les rapports

### `src/dashboard.py`
Interface Streamlit temps réel :
- Thème dark professionnel
- Graphiques Plotly avec concepts ICT
- Auto-refresh configurable
- Cards métriques responsives
- **📍 Proximité ICT** avec détails par concept
- **🎯 Setups de trading** avec raisons entrée/SL/TP

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
