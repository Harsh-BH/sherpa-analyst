"""Attack corpus for guard.check_sql: every case must be refused at the stated stage, with a reason
that names the offending thing. No database needed."""
import pytest
import sqlglot

from sherpa.contracts import QueryRejected
from sherpa.guard import check_sql

ATTACKS = [
    # id, sql, stage, reason substring
    ("stacked_select", "SELECT 1; SELECT 2", "parse", "Only one statement is allowed (found 2)"),
    ("stacked_drop", "SELECT txn_id FROM transactions; DROP TABLE analytics.transactions", "parse", "found 2"),
    ("comment_hidden_2nd", "SELECT 1 /* harmless; */ ; DELETE FROM analytics.transactions", "parse", "found 2"),
    ("syntax_error", "SELEC txn_id FROM transactions", "parse", "could not be parsed"),
    ("empty", "  ;  ", "parse", "No SQL statement"),
    ("set_config", "SELECT set_config('role', 'postgres', false)", "policy", "Function set_config is not allowed"),
    ("current_setting", "SELECT current_setting('is_superuser')", "policy", "Function current_setting"),
    ("pg_sleep", "SELECT pg_sleep(10)", "policy", "Function pg_sleep is not allowed"),
    ("pg_sleep_qualified", "SELECT pg_catalog.pg_sleep(1)", "policy", "Schema-qualified function"),
    ("shadowed_lower", "SELECT public.lower(status) FROM transactions", "policy", "Schema-qualified function"),
    ("set_role", "SET ROLE postgres", "policy", "SET statements are not allowed"),
    ("reset_role", "RESET ROLE", "policy", "RESET statements are not allowed"),
    ("set_session", "SET statement_timeout = 0", "policy", "SET"),
    ("dm_cte_delete", "WITH d AS (DELETE FROM analytics.transactions RETURNING txn_id) SELECT * FROM d",
     "policy", "CTE d must be a SELECT"),
    ("dm_cte_insert", "WITH i AS (INSERT INTO analytics.banks VALUES ('X','x','x') RETURNING bank_id) SELECT 1",
     "policy", "CTE i must be a SELECT"),
    ("select_into", "SELECT * INTO analytics.stolen FROM analytics.transactions", "policy", "SELECT ... INTO"),
    ("for_update", "SELECT txn_id FROM transactions FOR UPDATE", "policy", "FOR UPDATE / FOR SHARE"),
    ("for_share", "SELECT txn_id FROM transactions FOR SHARE", "policy", "FOR UPDATE / FOR SHARE"),
    ("copy_program", "COPY (SELECT 1) TO PROGRAM 'id'", "policy", "COPY statements are not allowed"),
    ("do_block", "DO $$ BEGIN PERFORM pg_sleep(1); END $$", "policy", "DO statements are not allowed"),
    ("call", "CALL do_something()", "policy", "CALL statements are not allowed"),
    ("explain_analyze_delete", "EXPLAIN ANALYZE DELETE FROM analytics.transactions", "policy", "EXPLAIN statements"),
    ("quoted_raw", 'SELECT * FROM "raw"."transaction_events"', "policy",
     "Table raw.transaction_events is outside the analytics schema"),
    ("raw_in_subquery", "SELECT n FROM (SELECT count(*) AS n FROM raw.transaction_events) s", "policy",
     "raw.transaction_events is outside"),
    ("raw_in_union", "SELECT txn_id FROM transactions UNION ALL SELECT txn_id FROM raw.transaction_events",
     "policy", "raw.transaction_events is outside"),
    ("raw_in_join", "SELECT t.txn_id FROM transactions t JOIN raw.merchants m ON m.merchant_id = t.merchant_id",
     "policy", "raw.merchants is outside"),
    ("app_runs", "SELECT question FROM app.runs", "policy", "app.runs is outside"),
    ("information_schema", "SELECT table_name FROM information_schema.tables", "policy",
     "information_schema.tables is outside"),
    ("pg_catalog", "SELECT rolname FROM pg_catalog.pg_roles", "policy", "pg_catalog.pg_roles is outside"),
    ("pg_catalog_unqualified", "SELECT relname FROM pg_class", "policy", "Table pg_class is not available"),
    ("cte_shadow_out_of_scope", "SELECT * FROM (WITH c AS (SELECT 1 AS a) SELECT a FROM c) x, c",
     "policy", "Table c is not available"),
    ("cte_named_pg", "WITH pg_class AS (SELECT 1 AS a) SELECT a FROM pg_class", "policy", "pg_class is reserved"),
    ("other_database", "SELECT 1 FROM otherdb.analytics.transactions", "policy", "outside the analytics schema"),
    ("lo_import", "SELECT lo_import('/etc/passwd')", "policy", "Function lo_import is not allowed"),
    ("dblink", "SELECT * FROM dblink('host=evil', 'select 1') AS t(a int)", "policy", "Function dblink is not allowed"),
    ("txid", "SELECT txid_current()", "policy", "Function txid_current"),
    ("nextval", "SELECT nextval('s')", "policy", "Function nextval"),
    ("pg_read_file", "SELECT pg_read_file('/etc/passwd')", "policy", "Function pg_read_file"),
    ("advisory_lock", "SELECT pg_advisory_lock(1)", "policy", "Function pg_advisory_lock"),
    ("query_to_xml", "SELECT query_to_xml('select * from raw.transaction_events', true, true, '')", "policy",
     "Function query_to_xml"),
    ("generate_series", "SELECT * FROM generate_series(1, 100000000) g", "policy", "Function generate_series is not allowed"),
    ("table_raw", "TABLE raw.transaction_events", "policy", "raw.transaction_events is outside"),
    ("values_pg_sleep", "VALUES ((SELECT pg_sleep(1)))", "policy", "VALUES statements are not allowed"),
    ("prepare", "PREPARE p AS SELECT 1", "policy", "PREPARE statements are not allowed"),
    ("listen", "LISTEN ch", "policy", "LISTEN statements are not allowed"),
    ("notify", "NOTIFY ch, 'x'", "parse", "could not be parsed"),
    ("vacuum", "VACUUM analytics.transactions", "policy", "VACUUM statements are not allowed"),
    ("begin", "BEGIN", "policy", "BEGIN"),
    ("insert", "INSERT INTO analytics.banks VALUES ('X', 'x', 'x')", "policy", "INSERT"),
    ("truncate", "TRUNCATE analytics.transactions", "policy", "TRUNCATE"),
    ("grant", "GRANT ALL ON analytics.transactions TO PUBLIC", "policy", "GRANT"),
    ("recursive_cte", "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r) SELECT n FROM r",
     "policy", "Recursive CTEs"),
    ("regclass_cast", "SELECT 'raw.transaction_events'::regclass", "policy", "Cast to type"),
    ("unknown_column", "SELECT foo FROM transactions", "policy", "Column foo does not exist or is not visible"),
    ("unknown_qualified_column", "SELECT t.password FROM transactions t", "policy", "Column password does not exist"),
    ("unknown_table", "SELECT * FROM analytics.secrets", "policy", "Table secrets is not available"),
]


@pytest.mark.parametrize("sql,stage,reason", [a[1:] for a in ATTACKS], ids=[a[0] for a in ATTACKS])
def test_attack_refused(sql, stage, reason):
    with pytest.raises(QueryRejected) as ei:
        check_sql(sql)
    assert ei.value.stage == stage, ei.value.reason
    assert reason in ei.value.reason
    assert ei.value.sql == sql


def test_corpus_size():
    assert len(ATTACKS) >= 25


def test_comment_hidden_statement_is_stripped():
    out = check_sql("SELECT txn_id FROM transactions -- ; DROP TABLE analytics.transactions").sql
    assert "DROP" not in out and "--" not in out and "/*" not in out


def test_complex_legit_query_passes():
    sql = """
        WITH daily AS (
            SELECT txn_date, payment_method,
                   SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS ok,
                   COUNT(*) FILTER (WHERE status IN ('SUCCESS', 'FAILED')) AS reached
            FROM transactions
            WHERE txn_date >= DATE '2026-11-01'
            GROUP BY 1, 2
        )
        SELECT d.txn_date, d.payment_method, b.name,
               ROUND(d.ok::numeric / NULLIF(d.reached, 0), 4) AS sr,
               AVG(d.ok::numeric / NULLIF(d.reached, 0)) OVER (PARTITION BY d.payment_method ORDER BY d.txn_date
                                                              ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS sr_7d,
               DATE_TRUNC('week', d.txn_date) AS wk
        FROM daily d
        LEFT JOIN analytics.banks b ON b.bank_id = d.payment_method
        ORDER BY d.txn_date
    """
    r = check_sql(sql)
    assert r.tables == ["banks", "transactions"]
    assert "analytics.transactions" in r.sql and "LIMIT 5001" in r.sql
    assert len(sqlglot.parse(r.sql, dialect="postgres")) == 1


def test_select_star_expands_to_allowed_columns_only():
    out = check_sql("SELECT * FROM banks").sql
    assert "banks.bank_id" in out and "banks.name" in out and "*" not in out


def test_limit_enforced():
    assert check_sql("SELECT txn_id FROM transactions", max_rows=100).sql.endswith("LIMIT 101")
    assert check_sql("SELECT txn_id FROM transactions LIMIT 10", max_rows=100).sql.endswith("LIMIT 10")
    assert check_sql("SELECT txn_id FROM transactions LIMIT 100000", max_rows=100).sql.endswith("LIMIT 101")
    assert check_sql("SELECT txn_id FROM transactions LIMIT ALL", max_rows=100).sql.endswith("LIMIT 101")
    assert check_sql("SELECT txn_id FROM transactions FETCH FIRST 50 ROWS ONLY", max_rows=100).sql.endswith("50 ROWS ONLY")
    assert check_sql("SELECT bank_id FROM banks UNION SELECT txn_id FROM transactions", max_rows=7).sql.endswith("LIMIT 8")


def test_unqualified_tables_are_pinned_to_analytics():
    r = check_sql("SELECT status FROM transactions")
    assert "FROM analytics.transactions" in r.sql and r.tables == ["transactions"]
