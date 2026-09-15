"""Text-to-SQL-Chatbot fuer Fragen zu den RIS-Daten (DuckDB, siehe database/db.py).

Ablauf pro Frage: (1) Claude erhaelt das live aus information_schema gelesene
Tabellenschema + eine kurze fachliche Legende und schreibt genau ein SELECT-Statement,
(2) das Statement wird gegen die read-only DuckDB-Verbindung ausgefuehrt, (3) Claude
formuliert aus dem Ergebnis eine Antwort in ganzen Saetzen. Die generierte SQL bleibt
fuer den Nutzer sichtbar (Transparenz/Nachvollziehbarkeit).
"""
import re

import anthropic

from config.settings import ANTHROPIC_API_KEY
from database.db import query_df

MODEL = 'claude-sonnet-5'
MAX_ROWS = 200
MAX_HISTORY_MESSAGES = 12  # 6 Frage/Antwort-Runden - begrenzt Kontextgroesse und Kosten bei langen Sessions

SCHEMA_NOTES = """
Fachliche Legende (RIS = Baubewilligungs- und Regulierungsdaten Schweizer Gemeinden):
- fact_project: eine Zeile pro Baugesuch. processing_days = Bearbeitungsdauer in Tagen
  zwischen Antrag (applied_date) und Bewilligung (approved_date).
- fact_municipality: eine Zeile pro Gemeinde mit Kennzahlen 2021-2024. share_gt_180 und
  share_gt_365 sind ANTEILE zwischen 0 und 1 (nicht Prozent) der Projekte mit
  Bearbeitungsdauer > 180 bzw. > 365 Tagen - fuer Prozent mit *100 multiplizieren.
- fact_ranking: peer_rank = Rang im Vergleichsgruppen-Ranking (1 = bester Wert);
  process_score/regulation_score/market_score/overall_score sind Scores je Gemeinde.
- fact_regulation: Kennzahlen zur Bauzonenordnung/zum Reglement je Gemeinde
  (complexity_index_raw, document_age in Jahren). Eine Gemeinde OHNE Zeile in
  fact_regulation hat kein erfasstes Reglement - fuer "wie viele/wie viel % Gemeinden
  haben eine Bauzonenordnung" immer gegen dim_municipality LEFT JOINen und auf
  IS NOT NULL / IS NULL pruefen, nicht einfach count(*) FROM fact_regulation.
- fact_document_validation: automatische Pruefung der Reglementsdokumente
  (Link/PDF gueltig, Metadaten/Hash-Aenderungen). validation_status='VALID' heisst
  technisch einwandfrei.
- dim_municipality.bfs_number ist die offizielle BFS-Gemeindenummer; Verknuepfung zum
  Kanton immer ueber dim_municipality.canton_id = dim_canton.canton_id.
- Tabellen mit Praefix stg_ sind Rohdaten-Staging-Tabellen - nicht verwenden, stattdessen
  die dim_/fact_/bridge_-Tabellen.
- Es existieren vorgefertigte Views mit bereits erledigten JOINs - wenn eine Frage dazu passt,
  bevorzuge sie gegenueber eigenen JOINs: vw_project_municipality (fact_project + Gemeinde/Kanton),
  vw_project_municipality_regulation (zusaetzlich + Reglementskennzahlen), vw_municipality_regulation
  (Gemeinde + Reglement), vw_regulation_quality (Reglement + Validierungsstatus),
  vw_document_validation_issues (nur fehlerhafte Dokumente), vw_current_law_document
  (aktuellste Dokumentversion je Gemeinde).
- dim_zone_parameter enthaelt sehr viele Bauzonen-Kennzahlen (Fassadenhoehe, Ausnuetzungsziffer
  etc.) je Zone/Gemeinde - nur verwenden, wenn die Frage explizit nach solchen baurechtlichen
  Kennzahlen fragt.
""".strip()

SQL_SYSTEM_TEMPLATE = """Du bist ein SQL-Assistent fuer eine DuckDB-Datenbank mit Schweizer \
Baubewilligungs- und Raumplanungsdaten (RIS). Du bekommst das Datenbankschema und eine Frage \
auf Deutsch. Antworte AUSSCHLIESSLICH mit einem einzigen SQL-Codeblock, der genau ein \
SELECT-Statement enthaelt (kein INSERT/UPDATE/DELETE/DDL, kein Semikolon-Statement-Stacking).

Der Chatverlauf kann vorherige Fragen und deine vorherigen SQL-Antworten enthalten. Behandle \
kurze Anschlussfragen (z.B. "und nach Kanton?", "nur fuer Bern", "was ist mit 2022?") als \
Praezisierung oder Variante der vorherigen Abfrage und baue konsistent darauf auf.

Schema:
{schema}

{notes}

Falls sich die Frage mit diesem Schema nicht beantworten laesst, antworte mit:
```sql
-- NICHT_BEANTWORTBAR: <kurzer Grund>
```
"""

ANSWER_SYSTEM = """Du bist ein Datenanalyst fuer eine Schweizer Raumplanungs-Plattform (RIS). \
Du bekommst eine Nutzerfrage, das dafuer ausgefuehrte SQL-Statement und das Abfrageergebnis. \
Formuliere daraus eine klare, praezise Antwort in ganzen deutschen Saetzen fuer eine \
Sachbearbeiterin - nenne konkrete Zahlen aus dem Ergebnis. Wenn das Ergebnis leer ist, sag das \
direkt. Erfinde keine Zahlen, die nicht im Ergebnis stehen."""

_FORBIDDEN = re.compile(
    r'\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|call|export|import|install|load)\b',
    re.IGNORECASE,
)


def _client():
    if not ANTHROPIC_API_KEY:
        raise RuntimeError('ANTHROPIC_API_KEY ist nicht gesetzt (.env prüfen).')
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def get_schema_text():
    df = query_df("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'main' AND table_name NOT LIKE 'stg\\_%' ESCAPE '\\'
        ORDER BY table_name, ordinal_position
    """)
    lines = []
    for table, group in df.groupby('table_name', sort=True):
        cols = ', '.join(f"{r.column_name} {r.data_type}" for r in group.itertuples())
        lines.append(f"{table}({cols})")
    return '\n'.join(lines)


def _extract_sql(text):
    match = re.search(r'```sql\s*(.*?)```', text, re.DOTALL | re.IGNORECASE)
    sql = (match.group(1) if match else text).strip().rstrip(';').strip()
    return sql


def _validate_sql(sql):
    if not sql or sql.upper().startswith('-- NICHT_BEANTWORTBAR'):
        return sql, 'NICHT_BEANTWORTBAR: ' + sql
    if ';' in sql:
        return None, 'Mehrere Statements sind nicht erlaubt.'
    if not re.match(r'^\s*(SELECT|WITH)\b', sql, re.IGNORECASE):
        return None, 'Nur SELECT-Abfragen sind erlaubt.'
    if _FORBIDDEN.search(sql):
        return None, 'Die generierte Abfrage enthaelt nicht erlaubte Schluesselwoerter.'
    return sql, None


def ask(question, history=None):
    """Beantwortet eine Datenfrage, optional mit Chatverlauf fuer Anschlussfragen.

    history: Liste von {'role': 'user'|'assistant', 'content': str} - fuer 'assistant'
    Eintraege die rohe SQL-Antwort aus einer vorherigen ask()-Rueckgabe (raw_sql_response),
    nicht die finale Formulierung, damit das Modell seine eigene vorherige Abfrage exakt
    wiedersieht statt eine Zusammenfassung davon. Gibt dict mit answer/sql/error/rows/
    raw_sql_response zurueck - raw_sql_response fuer die naechste ask()-Runde speichern.
    """
    client = _client()
    schema = get_schema_text()

    sql_messages = list(history or [])[-MAX_HISTORY_MESSAGES:]
    sql_messages.append({'role': 'user', 'content': question})

    sql_response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        cache_control={'type': 'ephemeral'},  # Schema+Legende sind pro Session stabil -> guenstiger Cache-Hit ab der 2. Frage
        system=SQL_SYSTEM_TEMPLATE.format(schema=schema, notes=SCHEMA_NOTES),
        messages=sql_messages,
    )
    raw_text = next((b.text for b in sql_response.content if b.type == 'text'), '')
    sql = _extract_sql(raw_text)
    sql, error = _validate_sql(sql)

    if error and sql is None:
        return {'answer': f'Ich konnte daraus keine gültige Abfrage bauen: {error}', 'sql': raw_text,
                'error': error, 'raw_sql_response': raw_text}
    if error:  # NICHT_BEANTWORTBAR
        reason = sql.split(':', 1)[-1].strip() if ':' in sql else ''
        return {'answer': f'Diese Frage lässt sich mit den vorhandenen Daten nicht beantworten. {reason}'.strip(),
                'sql': None, 'error': None, 'raw_sql_response': raw_text}

    try:
        result_df = query_df(sql)
    except Exception as exc:  # ungültiges SQL trotz Guard, z.B. unbekannte Spalte
        return {'answer': f'Die generierte Abfrage konnte nicht ausgeführt werden ({exc}).', 'sql': sql,
                'error': str(exc), 'raw_sql_response': raw_text}

    truncated = len(result_df) > MAX_ROWS
    result_for_prompt = result_df.head(MAX_ROWS)
    result_text = result_for_prompt.to_csv(index=False)
    if truncated:
        result_text += f'\n... ({len(result_df) - MAX_ROWS} weitere Zeilen abgeschnitten)'

    answer_response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=ANSWER_SYSTEM,
        messages=[{
            'role': 'user',
            'content': f'Frage: {question}\n\nSQL:\n{sql}\n\nErgebnis (CSV):\n{result_text}',
        }],
    )
    answer = next((b.text for b in answer_response.content if b.type == 'text'), '').strip()

    return {'answer': answer, 'sql': sql, 'error': None, 'rows': len(result_df), 'raw_sql_response': raw_text}
