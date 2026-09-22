import pandas as pd

from database.db import query_df, table_exists
from services.zone_params import ZONE_PARAM_TYPES

def metrics():
    if not table_exists('fact_project'): return {'projects':0,'municipalities':0,'median':None,'over180':None,'over365':None}
    r=query_df('''
        SELECT count(*) projects, count(DISTINCT BFS) municipalities, median(processing_days) median,
               avg(CASE WHEN processing_days>180 THEN 1 ELSE 0 END) over180,
               avg(CASE WHEN processing_days>365 THEN 1 ELSE 0 END) over365
        FROM fact_project
    ''').iloc[0]
    return r.to_dict()
def municipality_metrics():
    if not table_exists('fact_municipality'): return query_df('SELECT 1 WHERE false')
    return query_df('''
        SELECT dm.bfs_number AS BFS, fm.n_projects, fm.median_duration AS median_days,
               fm.complexity_index_raw AS complexity_index, fm.build_density
        FROM fact_municipality fm JOIN dim_municipality dm USING (municipality_id)
        WHERE fm.n_projects IS NOT NULL
    ''')
def project_types(limit=15):
    return query_df('''
        SELECT df.fsa_description AS fsa_text, count(*) n, median(fp.processing_days) median_days
        FROM fact_project fp
        JOIN bridge_project_fsa bpf ON bpf.PROJID=fp.PROJID AND bpf.IS_PRIMARY
        JOIN dim_fsa df ON df.fsa_code=bpf.FSA_CODE
        WHERE df.fsa_description IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT ?
    ''', [limit])
def projects_for_bfs(bfs):
    return query_df('''
        SELECT fp.PROJID, fp.processing_days, dd.devtype_description AS devtype_text, df.fsa_description AS fsa_text
        FROM fact_project fp
        LEFT JOIN bridge_project_devtype bpd ON bpd.PROJID=fp.PROJID AND bpd.IS_PRIMARY
        LEFT JOIN dim_devtype dd ON dd.devtype_code=bpd.DEVTYPE
        LEFT JOIN bridge_project_fsa bpf ON bpf.PROJID=fp.PROJID AND bpf.IS_PRIMARY
        LEFT JOIN dim_fsa df ON df.fsa_code=bpf.FSA_CODE
        WHERE fp.BFS=?
    ''',[int(bfs)])
def duplicate_summary():
    return query_df('''
        SELECT count(*) duplicate_projects, coalesce(sum(row_count-1),0) excess_rows FROM (
          SELECT PROJID, count(*) row_count FROM fact_project GROUP BY PROJID HAVING count(*)>1
        )
    ''').iloc[0].to_dict()
def duplicate_projects_detail(limit=100):
    return query_df('''
        SELECT PROJID, count(*) row_count, count(DISTINCT BFS) bfs_count
        FROM fact_project GROUP BY PROJID HAVING count(*)>1
        ORDER BY row_count DESC LIMIT ?
    ''', [limit])

def search_municipalities(term, limit=5):
    """Präfix-/Substring-Suche auf Gemeindenamen, für die Suche-Seite - erkennt
    reine Gemeinde-Eingaben, um direkt zur Analyse Gemeinden statt zur Adresssuche zu leiten."""
    return query_df('''
        SELECT dm.bfs_number AS BFS, dm.municipality_name, c.canton_code AS Kanton
        FROM dim_municipality dm LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        WHERE lower(dm.municipality_name) LIKE lower(?)
        ORDER BY (lower(dm.municipality_name) LIKE lower(?)) DESC, length(dm.municipality_name)
        LIMIT ?
    ''', [f'%{term}%', f'{term}%', limit])

def canton_options():
    return query_df('SELECT canton_id, canton_code, canton_name FROM dim_canton ORDER BY canton_code')

def ranking_table(canton_id=None):
    where = 'WHERE c.canton_id=?' if canton_id else ''
    params = [int(canton_id)] if canton_id else []
    return query_df(f'''
        SELECT dm.municipality_name, dm.bfs_number AS BFS, c.canton_code AS Kanton,
               fr.peer_rank, fr.process_score, fr.regulation_score, fr.market_score, fr.overall_score
        FROM fact_ranking fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        {where}
        ORDER BY fr.overall_score DESC
    ''', params)

def _regulation_filter_clause(canton_id, bfs, min_complexity, max_complexity, min_age, max_age, validation_status):
    clauses, params = [], []
    if bfs:
        clauses.append('dm.bfs_number=?'); params.append(int(bfs))
    elif canton_id:
        clauses.append('c.canton_id=?'); params.append(int(canton_id))
    if min_complexity is not None:
        clauses.append('fr.complexity_index_raw>=?'); params.append(min_complexity)
    if max_complexity is not None:
        clauses.append('fr.complexity_index_raw<=?'); params.append(max_complexity)
    if min_age is not None:
        clauses.append('fr.document_age>=?'); params.append(min_age)
    if max_age is not None:
        clauses.append('fr.document_age<=?'); params.append(max_age)
    if validation_status:
        clauses.append('dvi.validation_status=?'); params.append(validation_status)
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    return where, params

def regulation_table(canton_id=None, bfs=None, min_complexity=None, max_complexity=None,
                      min_age=None, max_age=None, validation_status=None):
    where, params = _regulation_filter_clause(canton_id, bfs, min_complexity, max_complexity, min_age, max_age, validation_status)
    return query_df(f'''
        SELECT dm.municipality_name, dm.bfs_number AS BFS, c.canton_code AS Kanton,
               fr.complexity_index_raw, fr.intervention_count, fr.architecture_count,
               fr.housing_count, fr.densification_count, fr.document_age, dvi.validation_status
        FROM fact_regulation fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        LEFT JOIN fact_document_validation dvi ON dvi.document_version_id=fr.document_version_id
        {where}
        ORDER BY fr.complexity_index_raw DESC
    ''', params)

def regulation_count(canton_id=None, bfs=None, min_complexity=None, max_complexity=None,
                      min_age=None, max_age=None, validation_status=None):
    where, params = _regulation_filter_clause(canton_id, bfs, min_complexity, max_complexity, min_age, max_age, validation_status)
    return query_df(f'''
        SELECT count(*) n
        FROM fact_regulation fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        LEFT JOIN fact_document_validation dvi ON dvi.document_version_id=fr.document_version_id
        {where}
    ''', params).iloc[0]['n']

def regulation_municipality_options():
    """Gemeinden mit Reglementsdaten (fact_regulation) - für den Gemeinde-Filter der
    Gemeinde-Reglemente-Tabelle, analog municipality_options() bei den Baugesuchen."""
    return query_df('''
        SELECT DISTINCT dm.bfs_number AS BFS, dm.municipality_name, c.canton_code AS Kanton
        FROM fact_regulation fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        ORDER BY dm.municipality_name
    ''')

def document_validation_status_counts():
    return query_df('SELECT validation_status, count(*) n FROM fact_document_validation GROUP BY 1 ORDER BY n DESC')

def document_validation_issues(limit=200):
    return query_df('''
        SELECT dm.municipality_name, dm.bfs_number AS BFS, mp.municipality_part_name,
               v.validation_status, v.linkdoc_present, v.link_valid, v.downloaded_pdf_valid,
               v.metadata_equal, v.hash_equal
        FROM vw_document_validation_issues v
        LEFT JOIN dim_municipality dm ON dm.municipality_id=v.municipality_id
        LEFT JOIN dim_municipality_part mp ON mp.municipality_part_id=v.municipality_part_id
        ORDER BY v.validation_status
        LIMIT ?
    ''', [limit])

def data_quality_summary():
    return query_df('''
        SELECT
          (SELECT count(*) FROM fact_document_validation) AS total_documents,
          (SELECT count(*) FROM fact_document_validation WHERE validation_status='VALID') AS valid_documents,
          (SELECT count(*) FROM fact_document_validation WHERE validation_status NOT IN ('VALID','CONTENT_CHANGED')) AS error_documents,
          (SELECT count(*) FROM (SELECT PROJID FROM fact_project GROUP BY PROJID HAVING count(*)>1)) AS duplicate_projects,
          (SELECT count(DISTINCT law_document_id) FROM (SELECT law_document_id FROM bridge_municipality_law GROUP BY law_document_id HAVING count(DISTINCT municipality_id)>1)) AS shared_documents
    ''').iloc[0].to_dict()

def devtype_breakdown(limit=15):
    return query_df('''
        SELECT dd.devtype_description AS devtype_text, count(*) n, median(fp.processing_days) median_days
        FROM fact_project fp
        JOIN bridge_project_devtype bpd ON bpd.PROJID=fp.PROJID AND bpd.IS_PRIMARY
        JOIN dim_devtype dd ON dd.devtype_code=bpd.DEVTYPE
        WHERE dd.devtype_description IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT ?
    ''', [limit])

def municipality_options():
    return query_df('''
        SELECT dm.bfs_number AS BFS, dm.municipality_name, c.canton_code AS Kanton
        FROM dim_municipality dm LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        WHERE dm.bfs_number IN (SELECT DISTINCT BFS FROM fact_project WHERE BFS IS NOT NULL)
        ORDER BY dm.municipality_name
    ''')

def municipality_summary(bfs):
    return query_df('''
        SELECT dm.municipality_name, c.canton_code AS Kanton, rb.peer_group,
               fm.n_projects, fm.median_duration, fm.complexity_index_raw, fm.build_density,
               fm.share_gt_180, fm.share_gt_365,
               fr.overall_score, fr.process_score, fr.regulation_score, fr.market_score,
               fr.peer_rank, rk.peer_group_size, rk.rank_gesamt_national
        FROM dim_municipality dm
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        LEFT JOIN fact_municipality fm ON fm.municipality_id=dm.municipality_id
        LEFT JOIN fact_ranking fr ON fr.municipality_id=dm.municipality_id
        LEFT JOIN stg_ranking_base rb ON rb.BFS=dm.bfs_number
        LEFT JOIN stg_ranking_ranking rk ON rk.BFS=dm.bfs_number
        WHERE dm.bfs_number=?
    ''', [int(bfs)])

def municipality_regulation_detail(bfs):
    return query_df('''
        SELECT fr.complexity_index_raw, fr.intervention_count, fr.architecture_count,
               fr.housing_count, fr.densification_count, fr.document_age,
               fr.densification_leitbild_count, fr.densification_aktivierung_count,
               fr.densification_mindest_count, fr.densification_bonus_count, fr.densification_auflagen_count,
               fr.housing_bezahlbarkeit_count, fr.housing_nutzung_count, fr.housing_erschliessung_count,
               dvi.validation_status, ld.canonical_url
        FROM fact_regulation fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        LEFT JOIN fact_document_validation dvi ON dvi.document_version_id=fr.document_version_id
        LEFT JOIN dim_document_version dv ON dv.document_version_id=fr.document_version_id
        LEFT JOIN dim_law_document ld ON ld.law_document_id=dv.law_document_id
        WHERE dm.bfs_number=?
    ''', [int(bfs)])

REGULATION_DEFINITIONS = {
    # Hauptkategorien (Analyse Reglemente - Übersichtschart)
    'Intervention': 'Zählt, wie oft im Reglement eine Instanz (z.B. Gemeinderat) nach eigenem '
                     'Ermessen einen Parameter anpassen kann (Interventionsmöglichkeit, '
                     'Verhandlungsspielraum, Leeway) – Mass für regulatorische Unschärfe, nicht '
                     'für Themenhäufigkeit.',
    'Architektur': 'Häufigkeit architekturbezogener Stichwörter im Reglementstext '
                    '(z.B. "gute Einpassung").',
    'Wohnen': 'Häufigkeit wohnbezogener Stichwörter im Reglementstext – Summe aus '
              'Bezahlbarkeit, Nutzung und Erschliessung.',
    'Verdichtung': 'Häufigkeit verdichtungsbezogener Stichwörter im Reglementstext – Summe aus '
                   'Leitbild, Aktivierung, Mindestvorgaben, Bonus und Auflagen.',
    # Sub-Kategorien Verdichtung
    'Leitbild': 'Erwähnungen eines städtebaulichen Leitbilds im Verdichtungskontext.',
    'Aktivierung': 'Erwähnungen von Aktivierungs-/Anreizmechanismen zur Verdichtung.',
    'Mindestvorgaben': 'Erwähnungen von Mindestdichte-Anforderungen.',
    'Bonus': 'Erwähnungen von Verdichtungsboni (z.B. zusätzliche Ausnützung bei Verdichtung).',
    'Auflagen': 'Erwähnungen von Auflagen/Bedingungen im Zusammenhang mit Verdichtung.',
    # Sub-Kategorien Wohnen
    'Bezahlbarkeit': 'Erwähnungen von bezahlbarem bzw. preisgünstigem Wohnraum.',
    'Nutzung': 'Erwähnungen von Wohnnutzungsvorschriften (z.B. Wohnanteil).',
    'Erschliessung': 'Erwähnungen der Erschliessung im Wohnkontext.',
}

def regulation_subcounts(bfs):
    """Detailaufschlüsselung der Verdichtung- und Wohnen-Stichwortzählungen für die
    Analyse Reglemente - Seite (aufklappbare Detailansicht pro Gemeinde) - Sub-Kategorien
    summieren sich exakt zu densification_count bzw. housing_count."""
    row = query_df('''
        SELECT fr.densification_leitbild_count, fr.densification_aktivierung_count,
               fr.densification_mindest_count, fr.densification_bonus_count, fr.densification_auflagen_count,
               fr.housing_bezahlbarkeit_count, fr.housing_nutzung_count, fr.housing_erschliessung_count
        FROM fact_regulation fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        WHERE dm.bfs_number=?
    ''', [int(bfs)])
    if row.empty:
        return pd.DataFrame(columns=['Oberbereich', 'Sub-Kategorie', 'n', 'Definition'])
    r = row.iloc[0]
    records = [
        {'Oberbereich': 'Verdichtung', 'Sub-Kategorie': 'Leitbild', 'n': r.densification_leitbild_count or 0},
        {'Oberbereich': 'Verdichtung', 'Sub-Kategorie': 'Aktivierung', 'n': r.densification_aktivierung_count or 0},
        {'Oberbereich': 'Verdichtung', 'Sub-Kategorie': 'Mindestvorgaben', 'n': r.densification_mindest_count or 0},
        {'Oberbereich': 'Verdichtung', 'Sub-Kategorie': 'Bonus', 'n': r.densification_bonus_count or 0},
        {'Oberbereich': 'Verdichtung', 'Sub-Kategorie': 'Auflagen', 'n': r.densification_auflagen_count or 0},
        {'Oberbereich': 'Wohnen', 'Sub-Kategorie': 'Bezahlbarkeit', 'n': r.housing_bezahlbarkeit_count or 0},
        {'Oberbereich': 'Wohnen', 'Sub-Kategorie': 'Nutzung', 'n': r.housing_nutzung_count or 0},
        {'Oberbereich': 'Wohnen', 'Sub-Kategorie': 'Erschliessung', 'n': r.housing_erschliessung_count or 0},
    ]
    for rec in records:
        rec['Definition'] = REGULATION_DEFINITIONS.get(rec['Sub-Kategorie'], '')
    return pd.DataFrame(records)

def map_data():
    return query_df('''
        SELECT dm.bfs_number AS BFS, dm.municipality_name, c.canton_code AS Kanton,
               co.Latitude, co.Longitude, fr.overall_score, fm.median_duration
        FROM dim_municipality dm
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        JOIN stg_coordinates co ON co.BFS=dm.bfs_number
        LEFT JOIN fact_ranking fr ON fr.municipality_id=dm.municipality_id
        LEFT JOIN fact_municipality fm ON fm.municipality_id=dm.municipality_id
        WHERE fr.overall_score IS NOT NULL
    ''')

def top_bottom_municipalities(n=10):
    df = query_df('''
        SELECT dm.municipality_name, c.canton_code AS Kanton, fr.overall_score
        FROM fact_ranking fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        WHERE fr.overall_score IS NOT NULL
        ORDER BY fr.overall_score DESC
    ''')
    return df.head(n), df.tail(n).sort_values('overall_score')

def regulation_vs_duration():
    return query_df('''
        SELECT dm.municipality_name, c.canton_code AS Kanton, fr.regulation_score,
               fm.median_duration, fm.n_projects
        FROM fact_ranking fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        LEFT JOIN fact_municipality fm ON fm.municipality_id=dm.municipality_id
        WHERE fr.regulation_score IS NOT NULL AND fm.median_duration IS NOT NULL
    ''')

def market_vs_duration():
    return query_df('''
        SELECT dm.municipality_name, c.canton_code AS Kanton, fr.market_score,
               fm.median_duration, fm.n_projects
        FROM fact_ranking fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        LEFT JOIN fact_municipality fm ON fm.municipality_id=dm.municipality_id
        WHERE fr.market_score IS NOT NULL AND fm.median_duration IS NOT NULL
    ''')

def quality_traffic():
    r = query_df('''
        SELECT count(*) n,
          avg(CASE WHEN downloaded_pdf_valid=false THEN 1 ELSE 0 END) pdf_error_share,
          avg(CASE WHEN hash_equal=false THEN 1 ELSE 0 END) hash_change_share,
          avg(CASE WHEN metadata_equal=false THEN 1 ELSE 0 END) metadata_conflict_share,
          avg(CASE WHEN link_valid=false OR linkdoc_present=false THEN 1 ELSE 0 END) link_error_share,
          avg(CASE WHEN municipality_exists=false THEN 1 ELSE 0 END) mapping_error_share
        FROM fact_document_validation
    ''').iloc[0]

    def level(share, green_max=0.05, yellow_max=0.2):
        if share is None or share != share: return 'green'
        return 'green' if share <= green_max else ('yellow' if share <= yellow_max else 'red')

    return [
        {'label': 'PDF Qualität', 'share': r.pdf_error_share, 'level': level(r.pdf_error_share)},
        {'label': 'Hash-Änderungen', 'share': r.hash_change_share, 'level': 'green',
         'note': 'Inhaltsänderung – kein automatischer Fehler'},
        {'label': 'Metadaten-Konflikte', 'share': r.metadata_conflict_share, 'level': level(r.metadata_conflict_share)},
        {'label': 'Linkfehler', 'share': r.link_error_share, 'level': level(r.link_error_share)},
        {'label': 'Gemeindemapping-Fehler', 'share': r.mapping_error_share, 'level': level(r.mapping_error_share)},
    ]

def etl_status():
    if not table_exists('etl_metadata'): return None
    return query_df('SELECT * FROM etl_metadata').iloc[0].to_dict()

def model_table_counts():
    tables = [
        ('dim_canton', 'Dimension'), ('dim_municipality', 'Dimension'), ('dim_municipality_part', 'Dimension'),
        ('dim_zone', 'Dimension'), ('dim_fsa', 'Dimension'), ('dim_devtype', 'Dimension'),
        ('dim_law_document', 'Dimension'), ('dim_document_version', 'Dimension'),
        ('fact_project', 'Fakt'), ('fact_municipality', 'Fakt'), ('fact_ranking', 'Fakt'),
        ('fact_regulation', 'Fakt'), ('fact_document_validation', 'Fakt'),
        ('bridge_project_fsa', 'Bridge'), ('bridge_project_devtype', 'Bridge'),
        ('bridge_project_zone', 'Bridge'), ('bridge_municipality_law', 'Bridge'),
    ]
    rows = []
    for name, kind in tables:
        if table_exists(name):
            n = query_df(f'SELECT count(*) n FROM {name}').iloc[0]['n']
        else:
            n = None
        rows.append({'Tabelle': name, 'Typ': kind, 'Zeilen': n})
    return pd.DataFrame(rows)

SUSTAINABILITY_TOPICS_SUPPORT_RESTRICT = {
    'solar': 'Solar', 'pv': 'Photovoltaik', 'wp': 'Wärmepumpe', 'fernwaerme': 'Fernwärme',
    'geo': 'Geothermie', 'daemmung': 'Dämmung', 'huelle': 'Gebäudehülle', 'minergie': 'Minergie',
    'energieeff': 'Energieeffizienz', 'biomasse': 'Biomasse',
}
SUSTAINABILITY_TOPICS_RESTRICT_ONLY = {
    'fossil': 'Fossile Heizung', 'oelheizung': 'Ölheizung', 'gasheizung': 'Gasheizung',
}

def municipality_sustainability(bfs):
    df = query_df('SELECT * FROM stg_ranking_nachhaltigkeit WHERE BFS=?', [int(bfs)])
    if df.empty:
        return {'supported': [], 'restricted': []}
    row = df.iloc[0]
    supported, restricted = [], []
    for key, label in SUSTAINABILITY_TOPICS_SUPPORT_RESTRICT.items():
        if row.get(f'{key}_support_dummy') == 1:
            supported.append(label)
        if row.get(f'{key}_restrict_dummy') == 1:
            restricted.append(label)
    for key, label in SUSTAINABILITY_TOPICS_RESTRICT_ONLY.items():
        if row.get(f'{key}_restricted_dummy') == 1:
            restricted.append(label)
    return {'supported': supported, 'restricted': restricted}

def municipality_yearly_volume(bfs):
    return query_df('''
        SELECT extract(year FROM applied_date) AS Jahr, count(*) AS Projekte
        FROM fact_project WHERE BFS=? AND applied_date IS NOT NULL
        GROUP BY 1 ORDER BY 1
    ''', [int(bfs)])

def municipality_documents(bfs):
    return query_df('''
        SELECT COALESCE(mp.municipality_part_name, '(Gesamtgemeinde)') AS Ortsteil,
               ld.canonical_url, dv.source_version, dvi.validation_status
        FROM bridge_municipality_law bl
        JOIN dim_municipality dm ON dm.municipality_id=bl.municipality_id
        LEFT JOIN dim_municipality_part mp ON mp.municipality_part_id=bl.municipality_part_id
        LEFT JOIN dim_document_version dv ON dv.document_version_id=bl.document_version_id
        LEFT JOIN dim_law_document ld ON ld.law_document_id=bl.law_document_id
        LEFT JOIN fact_document_validation dvi ON dvi.document_version_id=bl.document_version_id
        WHERE dm.bfs_number=?
    ''', [int(bfs)])

def municipality_benchmark(bfs):
    return query_df('''
        WITH target AS (
          SELECT dm.canton_id, fr.overall_score, fm.median_duration
          FROM dim_municipality dm
          LEFT JOIN fact_ranking fr ON fr.municipality_id=dm.municipality_id
          LEFT JOIN fact_municipality fm ON fm.municipality_id=dm.municipality_id
          WHERE dm.bfs_number=?
        )
        SELECT
          'Gemeinde' AS Ebene, t.overall_score AS Gesamt_Score, t.median_duration AS Median_Dauer
        FROM target t
        UNION ALL
        SELECT 'Kanton (Median)',
          median(fr.overall_score), median(fm.median_duration)
        FROM dim_municipality dm
        JOIN target t ON dm.canton_id=t.canton_id
        LEFT JOIN fact_ranking fr ON fr.municipality_id=dm.municipality_id
        LEFT JOIN fact_municipality fm ON fm.municipality_id=dm.municipality_id
        UNION ALL
        SELECT 'Schweiz (Median)', median(fr.overall_score), median(fm.median_duration)
        FROM fact_ranking fr LEFT JOIN fact_municipality fm ON fm.municipality_id=fr.municipality_id
    ''', [int(bfs)])

def municipality_diagnosis(bfs):
    """Einordnung/Priorisierung aus dem HSLU-Ranking (stg_ranking_ranking) - Pendant zur
    'EINORDNUNG GEMEINDE X'-Box im Excel-Gemeindereport. rating_eligibility='DROP' bedeutet
    zu wenig Projektdaten fuer ein Ranking (alle Scores dann NULL)."""
    return query_df('''
        SELECT rating_eligibility, rating_prozess, diagnose, prioritaet_partner,
               peer_group, peer_group_size, rank_gesamt_peer, rank_gesamt_national,
               national_percentile_gesamt
        FROM stg_ranking_ranking WHERE BFS=?
    ''', [int(bfs)])

DIMENSION_RANK_ROWS = [
    ('Prozess', 'score_prozess', 'rank_prozess_peer', 'national_percentile_prozess'),
    ('Regulierung', 'score_reglement_complexity', 'rank_regulierung_peer', 'national_percentile_regulierung'),
    ('Markt', 'score_markt', 'rank_markt_peer', 'national_percentile_markt'),
    ('Gesamt', 'score_gesamt_weighted', 'rank_gesamt_peer', 'national_percentile_gesamt'),
]

def municipality_dimension_ranks(bfs):
    """Score/Peer-Rang/Nat.-Perzentil je Dimension - Pendant zur 'PEER-VERGLEICH
    (Raumtyp_Gemeindegrösse)'-Tabelle im Excel-Gemeindereport."""
    row = query_df('''
        SELECT peer_group_size, score_prozess, score_reglement_complexity, score_markt,
               score_gesamt_weighted, rank_prozess_peer, rank_regulierung_peer, rank_markt_peer,
               rank_gesamt_peer, national_percentile_prozess, national_percentile_regulierung,
               national_percentile_markt, national_percentile_gesamt
        FROM stg_ranking_ranking WHERE BFS=?
    ''', [int(bfs)])
    if row.empty:
        return pd.DataFrame()
    r = row.iloc[0]
    return pd.DataFrame([{
        'Dimension': label, 'Score': r[score_col], 'Peer_Rang': r[rank_col],
        'Peer_Groesse': r['peer_group_size'], 'Nat_Perzentil': r[pct_col],
    } for label, score_col, rank_col, pct_col in DIMENSION_RANK_ROWS])

# stg_ranking_scores traegt bereits granulare 0-100-Scores pro Einzelmetrik (nicht nur die vier
# Verbund-Scores in stg_ranking_ranking). Die Achsen je Radar entsprechen bewusst exakt den
# Komponenten aus *_SCORE_WEIGHTS oben (Score-Berechnung/Transparenz) - so zeigen die Radar-
# Charts Gemeinde-vs-Peer je Score wirklich das, was in dessen Berechnung einfliesst, statt
# separater, teils andersartiger Kennzahlen (score_regulierung z.B. ist NICHT dasselbe wie
# score_reglement_complexity, und score_document_age_context fliesst gar nicht in die Score-
# Berechnung ein - beide bewusst nicht mehr Teil dieser Radar-Achsen).
GESAMT_RADAR_AXES = [
    ('Prozess', 'score_prozess'), ('Reglement', 'score_reglement_complexity'), ('Markt', 'score_markt'),
]
PROCESS_RADAR_AXES = [
    ('Median Dauer', 'score_median_duration'), ('SD Dauer', 'score_sd_duration'),
    ('> 180 Tage', 'score_share_gt_180'), ('> 365 Tage', 'score_share_gt_365'),
    ('Unapproved 2J', 'score_unapproved_2y'), ('Unapproved 3J', 'score_unapproved_3y'),
]
REGLEMENT_RADAR_AXES = [
    ('Intervention', 'score_intervention'), ('Architektur', 'score_architektur'),
    ('Verdichtung', 'score_verdichtung'), ('Wohnen', 'score_wohnen'),
]
MARKT_RADAR_AXES = [
    ('Leerwohnungsdruck', 'score_leerwohnungsdruck'), ('Bevölkerung', 'score_population'),
    ('MFH-Wachstum (CAGR)', 'score_mfh_cagr'),
]

def _score_radar(bfs, axes):
    """Gemeinde- vs. Peer-Group-Durchschnitt (nur rating_eligibility='OK') ueber die gegebenen
    0-100-Score-Spalten aus stg_ranking_scores, im Long-Format fuer den Radar-Chart."""
    cols = ', '.join(col for _, col in axes)
    row = query_df(f'SELECT peer_group, {cols} FROM stg_ranking_scores WHERE BFS=?', [int(bfs)])
    if row.empty or not row.iloc[0]['peer_group']:
        return pd.DataFrame(columns=['Achse', 'Wert', 'Serie'])
    r = row.iloc[0]
    peer_group = r['peer_group']
    agg_cols = ', '.join(f'avg({col}) AS {col}' for _, col in axes)
    peer = query_df(f"""
        SELECT {agg_cols} FROM stg_ranking_scores
        WHERE peer_group=? AND rating_eligibility='OK'
    """, [peer_group]).iloc[0]

    records = []
    for label, col in axes:
        records.append({'Achse': label, 'Wert': r[col], 'Serie': 'Gemeinde'})
        records.append({'Achse': label, 'Wert': peer[col], 'Serie': f'Peer-Ø ({peer_group})'})
    return pd.DataFrame(records)

def municipality_overview_radar(bfs):
    return _score_radar(bfs, GESAMT_RADAR_AXES)

def municipality_process_radar(bfs):
    return _score_radar(bfs, PROCESS_RADAR_AXES)

def municipality_reglement_radar(bfs):
    return _score_radar(bfs, REGLEMENT_RADAR_AXES)

def municipality_markt_radar(bfs):
    return _score_radar(bfs, MARKT_RADAR_AXES)

# Gewichte für die Score-Berechnung. Prozess- und Reglement-Gewichte stimmen exakt mit dem
# "Weights"-Sheet der Rohdaten-Excel überein (gegen alle 645 gerankten Gemeinden mit Diff=0.0
# verifiziert). Beim Markt-Score sind dort "Bevölkerung" und "MFH-Wohnungswachstum CAGR"
# vertauscht dokumentiert - eine freie lineare Regression gegen die echten score_markt-Werte
# ergab mit praktisch Null Residuum (~1e-14) die hier verwendeten, korrigierten Gewichte.
PROZESS_SCORE_WEIGHTS = [
    ('Median Bewilligungsdauer', 'score_median_duration', 0.30),
    ('Streuung (SD) der Dauer', 'score_sd_duration', 0.30),
    ('Anteil Verfahren > 180 Tage', 'score_share_gt_180', 0.15),
    ('Anteil Verfahren > 365 Tage', 'score_share_gt_365', 0.10),
    ('Unapproved nach 2 Jahren', 'score_unapproved_2y', 0.075),
    ('Unapproved nach 3 Jahren', 'score_unapproved_3y', 0.075),
]
REGLEMENT_SCORE_WEIGHTS = [
    ('Intervention', 'score_intervention', 0.40),
    ('Architektur', 'score_architektur', 0.20),
    ('Verdichtung', 'score_verdichtung', 0.20),
    ('Wohnen', 'score_wohnen', 0.20),
]
MARKT_SCORE_WEIGHTS = [
    ('Leerwohnungsdruck', 'score_leerwohnungsdruck', 0.70),
    ('Bevölkerung', 'score_population', 0.20),
    ('MFH-Wohnungswachstum (CAGR)', 'score_mfh_cagr', 0.10),
]

def _weighted_breakdown(row, weights):
    records, total = [], 0.0
    for label, col, w in weights:
        val = row.get(col)
        val = float(val) if val is not None and val == val else None
        contrib = (val or 0) * w
        total += contrib
        records.append({'Komponente': label, 'Gewicht': w, 'Wert': val, 'Beitrag': contrib})
    return total, records

def municipality_score_breakdown(bfs):
    """Rechnet Gesamt-/Prozess-/Reglement-/Markt-Score aus den granularen 0-100-Einzelscores in
    stg_ranking_scores selbst nach (Gewichte siehe *_SCORE_WEIGHTS oben) und stellt das Ergebnis
    dem Original-Wert aus der Ranking-Excel gegenüber - für die transparente
    Score-Aufschlüsselung in der Analyse Gemeinden. score_reglement_complexity ist die korrekte Quelle
    für den "Reglement"-Anteil (nicht score_regulierung, ein anderes, separates Feld - siehe
    docs/data_model.md)."""
    row = query_df('''
        SELECT score_prozess, score_reglement_complexity, score_markt, score_gesamt_weighted,
               score_median_duration, score_sd_duration, score_share_gt_180, score_share_gt_365,
               score_unapproved_2y, score_unapproved_3y,
               score_intervention, score_architektur, score_verdichtung, score_wohnen,
               score_leerwohnungsdruck, score_population, score_mfh_cagr
        FROM stg_ranking_scores WHERE BFS=?
    ''', [int(bfs)])
    if row.empty:
        return None
    r = row.iloc[0]

    prozess_calc, prozess_detail = _weighted_breakdown(r, PROZESS_SCORE_WEIGHTS)
    reglement_calc, reglement_detail = _weighted_breakdown(r, REGLEMENT_SCORE_WEIGHTS)
    markt_calc, markt_detail = _weighted_breakdown(r, MARKT_SCORE_WEIGHTS)
    gesamt_calc = 0.5 * prozess_calc + 0.3 * reglement_calc + 0.2 * markt_calc
    gesamt_detail = [
        {'Komponente': 'Prozess-Score', 'Gewicht': 0.50, 'Wert': prozess_calc, 'Beitrag': 0.5 * prozess_calc},
        {'Komponente': 'Reglement-Score', 'Gewicht': 0.30, 'Wert': reglement_calc, 'Beitrag': 0.3 * reglement_calc},
        {'Komponente': 'Markt-Score', 'Gewicht': 0.20, 'Wert': markt_calc, 'Beitrag': 0.2 * markt_calc},
    ]

    def clean(v):
        return None if v is None or v != v else float(v)

    return {
        'prozess': {'original': clean(r.score_prozess), 'berechnet': prozess_calc, 'detail': prozess_detail},
        'reglement': {'original': clean(r.score_reglement_complexity), 'berechnet': reglement_calc, 'detail': reglement_detail},
        'markt': {'original': clean(r.score_markt), 'berechnet': markt_calc, 'detail': markt_detail},
        'gesamt': {'original': clean(r.score_gesamt_weighted), 'berechnet': gesamt_calc, 'detail': gesamt_detail},
    }

PEER_BENCHMARK_METRICS = [
    ('Median Bearbeitungsdauer', 'median_duration', 'Tage', 'Prozess'),
    ('SD Bearbeitungsdauer', 'sd_duration', 'Tage', 'Prozess'),
    ('Anteil > 180 Tage', 'share_gt_180', '%', 'Prozess'),
    ('Anteil > 365 Tage', 'share_gt_365', '%', 'Prozess'),
    ('Unentschieden nach 2 Jahren', 'share_unapproved_after_2y', '%', 'Prozess'),
    ('Unentschieden nach 3 Jahren', 'share_unapproved_after_3y', '%', 'Prozess'),
    ('Intervention Count', 'Intervention_count', 'Anzahl', 'Regulierung'),
    ('Architektur Count', 'Architektur_count', 'Anzahl', 'Regulierung'),
    ('Verdichtung Count', 'Verdichtung_count', 'Anzahl', 'Regulierung'),
    ('Wohnen Count', 'Wohnen_count', 'Anzahl', 'Regulierung'),
    ('Leerstandsquote', 'leerwohnungsquote_2024', '%', 'Markt'),
    ('Ständige Bevölkerung', 'Staendige_Bevoelkerung_31_12_2024', 'Anzahl', 'Markt'),
    ('MFH-Wachstum (CAGR 21-24)', 'wohnungen_mfh_cagr_2021_2024', '%', 'Markt'),
]

def municipality_peer_benchmark(bfs):
    """Kennzahlen-Vergleich Gemeinde vs. Peer-Gruppen-Durchschnitt vs. nationaler Durchschnitt
    (nur rating_eligibility='OK' fuer die Durchschnitte) - Pendant zur 'GEMEINDE X ZAHLEN'-Tabelle
    im Excel-Gemeindereport. Rueckgabe: (DataFrame, peer_group_label)."""
    cols = ', '.join(col for _, col, _, _ in PEER_BENCHMARK_METRICS)
    row = query_df(f'SELECT peer_group, {cols} FROM stg_ranking_base WHERE BFS=?', [int(bfs)])
    if row.empty or not row.iloc[0]['peer_group']:
        return pd.DataFrame(), None
    r = row.iloc[0]
    peer_group = r['peer_group']

    agg_cols = ', '.join(f'avg({col}) AS {col}' for _, col, _, _ in PEER_BENCHMARK_METRICS)
    peer = query_df(f"""
        SELECT {agg_cols} FROM stg_ranking_base
        WHERE peer_group=? AND rating_eligibility='OK'
    """, [peer_group]).iloc[0]
    national = query_df(f"""
        SELECT {agg_cols} FROM stg_ranking_base WHERE rating_eligibility='OK'
    """).iloc[0]

    records = [{
        'Bereich': section, 'Dimension': label,
        'Gemeinde': r[col], 'Peer_Oe': peer[col], 'Nat_Oe': national[col], 'Einheit': unit,
    } for label, col, unit, section in PEER_BENCHMARK_METRICS]
    return pd.DataFrame(records), peer_group

def permit_duration_benchmark(bfs=None, canton_code=None):
    """Bearbeitungsdauer-Perzentile (Tage) auf drei Vergleichsebenen für den
    Permit-Intelligence-Report: national ("Comparable permits", alle Baugesuche als
    breite Vergleichsbasis), Kanton und Gemeinde - jeweils aus fact_project berechnet."""
    def level(where, params):
        row = query_df(f'''
            SELECT count(*) n, median(fp.processing_days) p50,
                   quantile_cont(fp.processing_days, 0.75) p75,
                   quantile_cont(fp.processing_days, 0.9) p90,
                   quantile_cont(fp.processing_days, 0.95) p95
            FROM fact_project fp
            LEFT JOIN dim_municipality dm ON dm.bfs_number = fp.BFS
            LEFT JOIN dim_canton c ON c.canton_id = dm.canton_id
            WHERE fp.processing_days IS NOT NULL {where}
        ''', params)
        if row.empty:
            return {'n': 0, 'p50': None, 'p75': None, 'p90': None, 'p95': None}
        r = row.iloc[0].to_dict()
        return {k: (None if v != v else v) for k, v in r.items()}  # NaN -> None (JSON/dcc.Store-safe)

    return {
        'national': level('', []),
        'canton': level('AND c.canton_code=?', [canton_code]) if canton_code else level('AND false', []),
        'municipality': level('AND fp.BFS=?', [int(bfs)]) if bfs else level('AND false', []),
    }

def national_reference():
    """Landesweite Mediane als Vergleichsmassstab für die qualitative Risikoeinschätzung
    (z.B. ist der Anteil Verfahren >1 Jahr dieser Gemeinde über- oder unterdurchschnittlich)."""
    row = query_df('''
        SELECT (SELECT median(share_gt_365) FROM fact_municipality) AS share_gt_365,
               (SELECT median(regulation_score) FROM fact_ranking) AS regulation_score
    ''')
    r = row.iloc[0].to_dict()
    return {k: (None if v != v else v) for k, v in r.items()}

def project_filter_options():
    """Auswahllisten (Kanton bereits über canton_options()) für die Baugesuche-Projekttabelle:
    Gebäudefunktion (FSA) und Baumassnahmenart (Devtype), jeweils nur Werte, die auch als
    Primärkategorie an mindestens einem Projekt hängen (bpf/bpd.IS_PRIMARY)."""
    fsa = query_df('''
        SELECT DISTINCT df.fsa_code, df.fsa_description
        FROM dim_fsa df JOIN bridge_project_fsa bpf ON bpf.FSA_CODE=df.fsa_code AND bpf.IS_PRIMARY
        WHERE df.fsa_description IS NOT NULL ORDER BY df.fsa_description
    ''')
    devtype = query_df('''
        SELECT DISTINCT dd.devtype_code, dd.devtype_description
        FROM dim_devtype dd JOIN bridge_project_devtype bpd ON bpd.DEVTYPE=dd.devtype_code AND bpd.IS_PRIMARY
        WHERE dd.devtype_description IS NOT NULL ORDER BY dd.devtype_description
    ''')
    return fsa, devtype

def _projects_filter_clause(canton_id, bfs, fsa_code, devtype_code, min_days, max_days, date_from, date_to):
    joins, clauses, params = '', [], []
    if fsa_code:
        joins += ' JOIN bridge_project_fsa bpf ON bpf.PROJID=fp.PROJID AND bpf.IS_PRIMARY'
        clauses.append('bpf.FSA_CODE=?'); params.append(fsa_code)
    if devtype_code:
        joins += ' JOIN bridge_project_devtype bpd ON bpd.PROJID=fp.PROJID AND bpd.IS_PRIMARY'
        clauses.append('bpd.DEVTYPE=?'); params.append(devtype_code)
    if bfs:
        clauses.append('fp.BFS=?'); params.append(int(bfs))
    elif canton_id:
        clauses.append('c.canton_id=?'); params.append(int(canton_id))
    if min_days is not None:
        clauses.append('fp.processing_days>=?'); params.append(min_days)
    if max_days is not None:
        clauses.append('fp.processing_days<=?'); params.append(max_days)
    if date_from:
        clauses.append('fp.applied_date>=?'); params.append(date_from)
    if date_to:
        clauses.append('fp.applied_date<=?'); params.append(date_to)
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    return joins, where, params

def projects_table(canton_id=None, bfs=None, fsa_code=None, devtype_code=None, min_days=None, max_days=None,
                    date_from=None, date_to=None, limit=500):
    joins, where, params = _projects_filter_clause(canton_id, bfs, fsa_code, devtype_code, min_days, max_days, date_from, date_to)
    return query_df(f'''
        SELECT fp.PROJID, dm.municipality_name, c.canton_code AS Kanton, fp.applied_date,
               fp.approved_date, fp.processing_days
        FROM fact_project fp
        LEFT JOIN dim_municipality dm ON dm.bfs_number=fp.BFS
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        {joins}
        {where}
        ORDER BY fp.applied_date DESC
        LIMIT ?
    ''', params + [limit])

def projects_count(canton_id=None, bfs=None, fsa_code=None, devtype_code=None, min_days=None, max_days=None,
                    date_from=None, date_to=None):
    joins, where, params = _projects_filter_clause(canton_id, bfs, fsa_code, devtype_code, min_days, max_days, date_from, date_to)
    return query_df(f'''
        SELECT count(*) n
        FROM fact_project fp
        LEFT JOIN dim_municipality dm ON dm.bfs_number=fp.BFS
        LEFT JOIN dim_canton c ON c.canton_id=dm.canton_id
        {joins}
        {where}
    ''', params).iloc[0]['n']

def zone_parameter_coverage():
    """Für jeden der 28 Zonenparameter-Typen: Anteil der Zonen in dim_zone_parameter (14'125
    Gemeinde/Zone-Kombinationen aus data_hslu260312.csv, die gesamtschweizerische Datenbasis),
    für die mindestens ein Wert (Standard/Bonus/Arealüberbauung) erfasst ist, sowie die Anzahl
    DISTINCT Gemeinden (BFS) mit mindestens einer solchen Zone - eine Gemeinde hat meist mehrere
    Zonen, daher ist die Gemeinden-Anzahl je Parameter nicht einfach proportional zum Zonen-
    Anteil. dim_zone_parameter deckt nur Zonen ab, zu denen auch tatsächlich Baugesuche
    vorliegen - "Schweiz" heisst hier also die 14'125 in den Rohdaten vorkommenden Zonen bzw.
    die 1'320 darin vorkommenden Gemeinden, nicht alle theoretisch existierenden."""
    if not table_exists('dim_zone_parameter'):
        return pd.DataFrame(columns=['Parameter', 'n_covered', 'coverage_pct', 'n_municipalities']), 0, 0
    exprs = ', '.join(
        f'count(*) FILTER (WHERE "{slug}_standard_value" IS NOT NULL OR "{slug}_bonus_value" IS NOT NULL '
        f'OR "{slug}_arealueberbauung_value" IS NOT NULL) AS "{slug}", '
        f'count(DISTINCT CASE WHEN "{slug}_standard_value" IS NOT NULL OR "{slug}_bonus_value" IS NOT NULL '
        f'OR "{slug}_arealueberbauung_value" IS NOT NULL THEN BFS END) AS "{slug}__gem"'
        for _, slug in ZONE_PARAM_TYPES
    )
    row = query_df(f'SELECT {exprs}, count(*) AS total, count(DISTINCT BFS) AS total_municipalities FROM dim_zone_parameter').iloc[0]
    total = int(row['total'])
    total_municipalities = int(row['total_municipalities'])
    records = [
        {
            'Parameter': label, 'n_covered': int(row[slug]), 'coverage_pct': (row[slug] / total) if total else None,
            'n_municipalities': int(row[f'{slug}__gem']),
        }
        for label, slug in ZONE_PARAM_TYPES
    ]
    df = pd.DataFrame(records).sort_values('coverage_pct', ascending=False).reset_index(drop=True)
    return df, total, total_municipalities

def municipality_parameter_ranking(limit=15):
    """Rangliste der Gemeinden nach Anzahl unterschiedlicher Zonenparameter-Typen (von 28), für
    die mindestens eine ihrer Zonen einen Wert hat - eine Gemeinde mit mehreren Zonen zählt
    einen Parameter nur einmal, auch wenn er in mehreren ihrer Zonen vorkommt (Vereinigung über
    die Zonen der Gemeinde, nicht Summe)."""
    if not table_exists('dim_zone_parameter'):
        return pd.DataFrame(columns=['municipality_name', 'Kanton', 'BFS', 'n_parameters'])
    per_bfs_exprs = ', '.join(
        f'max(CASE WHEN "{slug}_standard_value" IS NOT NULL OR "{slug}_bonus_value" IS NOT NULL '
        f'OR "{slug}_arealueberbauung_value" IS NOT NULL THEN 1 ELSE 0 END) AS "{slug}"'
        for _, slug in ZONE_PARAM_TYPES
    )
    sum_expr = ' + '.join(f'"{slug}"' for _, slug in ZONE_PARAM_TYPES)
    return query_df(f'''
        WITH per_bfs AS (
          SELECT BFS, {per_bfs_exprs}
          FROM dim_zone_parameter
          GROUP BY BFS
        )
        SELECT dm.municipality_name, c.canton_code AS Kanton, per_bfs.BFS, ({sum_expr}) AS n_parameters
        FROM per_bfs
        JOIN dim_municipality dm ON dm.bfs_number = per_bfs.BFS
        LEFT JOIN dim_canton c ON c.canton_id = dm.canton_id
        ORDER BY n_parameters DESC
        LIMIT ?
    ''', [limit])
