"""The schema contract: every `opportunities` column that shipped code names
must actually exist in a deployed database.

This file exists because of a real, days-long production outage. The promoted
`authority_cui`/`award_criterion` columns went out in a deploy, but schema.sql
— which is applied by hand in the Supabase SQL editor — never was. Postgres
answered `UndefinedColumnError: column "authority_cui" does not exist` for:

  * every authenticated read  (`get_ranked_opportunities` filters on it), and
  * every ingestion upsert    (`upsert_opportunity` inserts it),

so the whole signed-in product 500'd and not one new opportunity was persisted,
while the public routes — which never name these columns — kept answering fine.
That asymmetry is exactly why it read as a frontend bug for days.

The invariant below is what actually prevents a recurrence: a column the code
dereferences by name is either in the base CREATE TABLE (present in every
database that has ever run schema.sql) or in `db._REQUIRED_DDL` (applied at
boot by `db.ensure_schema`). Anything else is a column that exists only in a
file someone has to remember to run.
"""

import inspect
import re
from pathlib import Path

import db

SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "schema.sql").read_text()


def _base_table_columns() -> set:
    """Columns in the original CREATE TABLE — present wherever schema.sql ran."""
    block = re.search(
        r"CREATE TABLE IF NOT EXISTS opportunities \((.*?)\n\);",
        SCHEMA_SQL,
        re.DOTALL,
    )
    assert block, "opportunities CREATE TABLE not found in schema.sql"
    columns = set()
    for line in block.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        name = line.split()[0]
        if name.upper() not in {"PRIMARY", "UNIQUE", "CONSTRAINT", "FOREIGN", "CHECK"}:
            columns.add(name)
    return columns


def _boot_ddl_columns() -> set:
    """Columns db.ensure_schema() guarantees on every start-up."""
    return {
        m.group(1)
        for stmt in db._REQUIRED_DDL
        if (m := re.search(r"ADD COLUMN IF NOT EXISTS (\w+)", stmt))
    }


def _insert_columns() -> set:
    """The column list upsert_opportunity actually INSERTs."""
    src = inspect.getsource(db.upsert_opportunity)
    block = re.search(r"INSERT INTO opportunities \((.*?)\)\s*VALUES", src, re.DOTALL)
    assert block, "could not locate the INSERT column list in upsert_opportunity"
    return {
        c.strip()
        for c in block.group(1).replace("\n", " ").split(",")
        if c.strip() and c.strip() != "now()"
    }


def _ranked_filter_columns() -> set:
    """Columns the ranked feed puts in a real WHERE clause."""
    src = inspect.getsource(db.get_ranked_opportunities)
    where = re.search(r"FROM opportunities\s+WHERE(.*?)(?:--|ORDER BY)", src, re.DOTALL)
    assert where, "could not locate the WHERE clause in get_ranked_opportunities"
    return set(re.findall(r"(\w+) = \$\d+", where.group(1)))


class TestEveryNamedColumnIsGuaranteed:
    def test_upsert_columns_all_exist_in_a_deployed_database(self):
        available = _base_table_columns() | _boot_ddl_columns()
        missing = _insert_columns() - available
        assert not missing, (
            f"upsert_opportunity INSERTs {sorted(missing)}, which is neither in the base "
            "CREATE TABLE nor in db._REQUIRED_DDL. Every ingestion upsert will raise "
            "UndefinedColumnError against any database where schema.sql was not applied "
            "by hand. Add the ALTER to db._REQUIRED_DDL (and to schema.sql)."
        )

    def test_ranked_feed_filter_columns_all_exist_in_a_deployed_database(self):
        available = _base_table_columns() | _boot_ddl_columns()
        missing = _ranked_filter_columns() - available
        assert not missing, (
            f"get_ranked_opportunities filters on {sorted(missing)}, which is neither in "
            "the base CREATE TABLE nor in db._REQUIRED_DDL. Every authenticated feed and "
            "market-trends request will 500. Add the ALTER to db._REQUIRED_DDL."
        )

    def test_the_columns_from_the_outage_are_specifically_covered(self):
        """Pins the exact three that took production down."""
        available = _base_table_columns() | _boot_ddl_columns()
        for column in ("authority_cui", "award_criterion", "procedure_type"):
            assert column in available, f"{column} lost its schema guarantee"


class TestBootDdlStaysSafeToRunUnconditionally:
    """ensure_schema runs on every boot, so a non-idempotent or destructive
    statement here would run against production repeatedly."""

    def test_every_statement_is_idempotent(self):
        for stmt in db._REQUIRED_DDL:
            assert "IF NOT EXISTS" in stmt, f"not idempotent: {stmt}"

    def test_nothing_destructive(self):
        forbidden = ("DROP", "TRUNCATE", "DELETE", "UPDATE", "RENAME", "ALTER COLUMN")
        for stmt in db._REQUIRED_DDL:
            upper = stmt.upper()
            for word in forbidden:
                assert word not in upper, f"destructive statement in boot DDL: {stmt}"

    def test_only_touches_the_opportunities_table(self):
        for stmt in db._REQUIRED_DDL:
            assert "opportunities" in stmt, f"unexpected table in boot DDL: {stmt}"

    def test_schema_sql_still_declares_everything_the_boot_ddl_does(self):
        """schema.sql stays the source of truth; the boot DDL is a subset of
        it, never a second, diverging definition."""
        for column in _boot_ddl_columns():
            assert re.search(
                rf"ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS {column}\b", SCHEMA_SQL
            ), f"{column} is applied at boot but absent from schema.sql"
