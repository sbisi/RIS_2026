-- Normalisierte Analytics-Schicht. Views werden nur angelegt, wenn Kerntabellen vorhanden sind.
CREATE OR REPLACE VIEW v_project AS
SELECT
  TRY_CAST(p.PROJID AS BIGINT) PROJID,
  TRY_CAST(p.BFS AS INTEGER) BFS,
  TRY_CAST(p.processing_days AS DOUBLE) processing_days,
  TRY_CAST(p.PLANNING_APPLICATION AS DATE) applied_date,
  TRY_CAST(p.PLANS_APPROVED AS DATE) approved_date,
  TRY_CAST(p.TENURE_TYPE AS INTEGER) tenure_type,
  TRY_CAST(p.FSACODE_1 AS INTEGER) fsacode_primary,
  COALESCE(p.FSACODE_1_TEXT, CAST(p.FSACODE_1 AS VARCHAR)) fsa_text,
  TRY_CAST(p.DEVTYPE_1 AS INTEGER) devtype_primary,
  COALESCE(dt.descr, CAST(p.DEVTYPE_1 AS VARCHAR)) devtype_text,
  TRY_CAST(p.build_density AS DOUBLE) build_density,
  TRY_CAST(p.complexity_index_raw AS DOUBLE) complexity_index_raw,
  TRY_CAST(p.zone_area_m2 AS DOUBLE) zone_area_m2
FROM raw_project p
LEFT JOIN lu_devtype dt ON TRY_CAST(p.DEVTYPE_1 AS INTEGER) = TRY_CAST(dt.code AS INTEGER);

CREATE OR REPLACE VIEW v_project_unique AS
SELECT * EXCLUDE(rn) FROM (
 SELECT *, row_number() OVER(PARTITION BY PROJID ORDER BY approved_date DESC NULLS LAST, applied_date DESC NULLS LAST) rn
 FROM v_project
) WHERE rn=1;

CREATE OR REPLACE VIEW v_municipality AS
SELECT TRY_CAST(BFS AS INTEGER) BFS, * EXCLUDE(BFS) FROM raw_municipality;

CREATE OR REPLACE VIEW v_municipality_metrics AS
SELECT
 BFS,
 count(*) n_projects,
 median(processing_days) median_days,
 avg(processing_days) mean_days,
 stddev_samp(processing_days) sd_days,
 avg(CASE WHEN processing_days>180 THEN 1 ELSE 0 END) share_over_180,
 avg(CASE WHEN processing_days>365 THEN 1 ELSE 0 END) share_over_365,
 median(complexity_index_raw) complexity_index,
 median(build_density) build_density
FROM v_project_unique
GROUP BY BFS;

CREATE OR REPLACE VIEW v_project_duplicates AS
SELECT PROJID, count(*) row_count, count(DISTINCT BFS) bfs_count
FROM v_project GROUP BY PROJID HAVING count(*)>1;

CREATE OR REPLACE VIEW v_project_fsa AS
UNPIVOT (
  SELECT PROJID,
    CAST(FSACODE_1 AS VARCHAR) FSACODE_1, CAST(FSACODE_2 AS VARCHAR) FSACODE_2,
    CAST(FSACODE_3 AS VARCHAR) FSACODE_3, CAST(FSACODE_4 AS VARCHAR) FSACODE_4,
    CAST(FSACODE_5 AS VARCHAR) FSACODE_5, CAST(FSACODE_6 AS VARCHAR) FSACODE_6,
    CAST(FSACODE_7 AS VARCHAR) FSACODE_7, CAST(FSACODE_8 AS VARCHAR) FSACODE_8,
    CAST(FSACODE_9 AS VARCHAR) FSACODE_9, CAST(FSACODE_10 AS VARCHAR) FSACODE_10,
    CAST(FSACODE_11 AS VARCHAR) FSACODE_11, CAST(FSACODE_12 AS VARCHAR) FSACODE_12
  FROM raw_project
) ON COLUMNS(c -> c LIKE 'FSACODE_%') INTO NAME source_column VALUE code;

CREATE OR REPLACE VIEW v_project_devtype AS
UNPIVOT raw_project ON COLUMNS(c -> c LIKE 'DEVTYPE_%' AND c NOT LIKE '%_TEXT') INTO NAME source_column VALUE code;
