# HSLU RIS Gemeinderanking Dashboard

Lokale Visual-Studio-Code-Anwendung für grosse Projekt-, Gemeinde- und Reglementdaten. Die App nutzt DuckDB und lädt nicht den gesamten 3-GB-Datenbestand in den Arbeitsspeicher.

## 1. Dateien ablegen
Kopiere mindestens diese Dateien nach `data/raw/`:

- `project_level.csv`
- `municipality_level.csv`
- `HSLU_Gemeinderanking_260811.xlsx` optional
- `gemeinden_koordinaten.xlsx` optional
- `devtype_lu.csv`, `fsa_lu.csv`, `tenure_lu.csv`, `cs_code_lu.csv` optional
- `results_law_Manager_260910.csv` optional

## 2. Installation unter Windows / VS Code
Öffne den Projektordner in Visual Studio Code und führe aus:

```powershell
.\scripts\setup_windows.bat
```

Alternativ manuell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

## 3. Datenbank aufbauen

```powershell
python -m etl.build_database
```

Die ETL-Schicht erstellt:

- `v_project`: harmonisierte Projektzeilen
- `v_project_unique`: ein Datensatz pro `PROJID`
- `v_municipality_metrics`: robuste Gemeindeaggregate
- `v_project_duplicates`: Mehrfachzeilen und Redundanzen
- Long-Views für FSA-, DEVTYPE- und CS-Codes

## 4. App starten

```powershell
python app.py
```

Danach im Browser öffnen: `http://127.0.0.1:8050`

## Fachliche Hinweise

- Projektzahlen immer mit eindeutiger `PROJID` berechnen.
- Gemeindekennzahlen nicht als unabhängige Projektbeobachtungen interpretieren.
- Geometrien und Reglementdokumente in einer nächsten Ausbaustufe normalisieren.
- Das in der Ranking-Seite berechnete Ranking ist ein technisches Beispiel. Für Publikationen die offizielle HSLU-Scoremethodik verwenden.
