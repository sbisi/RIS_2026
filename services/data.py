from database.db import query_df, table_exists

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
    reine Gemeinde-Eingaben, um direkt zum Gemeindeprofil statt zur Adresssuche zu leiten."""
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
               dvi.validation_status, ld.canonical_url
        FROM fact_regulation fr
        JOIN dim_municipality dm ON dm.municipality_id=fr.municipality_id
        LEFT JOIN fact_document_validation dvi ON dvi.document_version_id=fr.document_version_id
        LEFT JOIN dim_document_version dv ON dv.document_version_id=fr.document_version_id
        LEFT JOIN dim_law_document ld ON ld.law_document_id=dv.law_document_id
        WHERE dm.bfs_number=?
    ''', [int(bfs)])

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
    import pandas as pd
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
    joins, clauses, params = '