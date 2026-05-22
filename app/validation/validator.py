from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp


BLOCKED_NODES: tuple[type, ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Create,
    exp.Command,  # GRANT, REVOKE, COPY land here
)


@dataclass
class ValidationResult:
    ok: bool
    sql: str
    issues: list[str] = field(default_factory=list)
    used_tables: list[str] = field(default_factory=list)
    used_columns: list[tuple[str, str]] = field(default_factory=list)


class SQLValidator:
    def __init__(
        self, allowed_schema: dict[str, list[str]], dialect: str = "postgres"
    ):
        """allowed_schema maps table_name -> list of column_names.
        dialect is the sqlglot dialect name ("postgres", "sqlite", ...).
        """
        self._schema = {t.lower(): {c.lower() for c in cols} for t, cols in allowed_schema.items()}
        self._dialect = dialect

    def validate(self, sql: str, max_rows: int) -> ValidationResult:
        issues: list[str] = []
        if not sql.strip():
            return ValidationResult(ok=False, sql=sql, issues=["Empty SQL."])

        try:
            statements = sqlglot.parse(sql, read=self._dialect)
        except sqlglot.errors.ParseError as e:
            return ValidationResult(ok=False, sql=sql, issues=[f"Parse error: {e}"])

        statements = [s for s in statements if s is not None]
        if len(statements) != 1:
            return ValidationResult(ok=False, sql=sql, issues=["Exactly one statement is allowed."])

        tree = statements[0]

        # Must be a Select (allow With wrapping a Select)
        root = tree
        if isinstance(root, exp.With):
            root = root.this
        if not isinstance(root, exp.Select):
            return ValidationResult(ok=False, sql=sql, issues=["Only SELECT statements are allowed."])

        # Block destructive nodes anywhere in tree
        for node in tree.walk():
            if isinstance(node, BLOCKED_NODES):
                return ValidationResult(
                    ok=False,
                    sql=sql,
                    issues=[f"Disallowed statement type: {type(node).__name__}"],
                )

        # Collect tables & columns
        used_tables: list[str] = []
        for t in tree.find_all(exp.Table):
            name = t.name.lower()
            if name and name not in used_tables:
                used_tables.append(name)

        used_columns: list[tuple[str, str]] = []
        for c in tree.find_all(exp.Column):
            col = c.name.lower()
            tbl = c.table.lower() if c.table else ""
            used_columns.append((tbl, col))

        unknown_tables = [t for t in used_tables if t not in self._schema]
        if unknown_tables:
            issues.append(f"Unknown tables: {sorted(set(unknown_tables))}")

        # Column existence check: only validate where we can resolve the table.
        cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
        alias_to_table: dict[str, str] = {}
        for t in tree.find_all(exp.Table):
            alias = (t.alias or t.name).lower()
            alias_to_table[alias] = t.name.lower()

        unknown_columns: list[str] = []
        for tbl_alias, col in used_columns:
            if col == "*":
                continue
            real_table = alias_to_table.get(tbl_alias, tbl_alias)
            if not real_table:
                # Unqualified column with multiple tables in scope -- skip strict check.
                continue
            if real_table in cte_names:
                continue
            if real_table not in self._schema:
                continue  # already reported via unknown_tables
            if col not in self._schema[real_table]:
                unknown_columns.append(f"{real_table}.{col}")
        if unknown_columns:
            issues.append(f"Unknown columns: {sorted(set(unknown_columns))}")

        # Enforce a LIMIT (inject if missing)
        final_sql = sql
        if root.args.get("limit") is None:
            root.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
            final_sql = tree.sql(dialect=self._dialect)
        else:
            limit_node = root.args["limit"]
            try:
                limit_val = int(limit_node.expression.this)
                if limit_val > max_rows:
                    limit_node.expression.set("this", str(max_rows))
                    final_sql = tree.sql(dialect=self._dialect)
            except (AttributeError, ValueError, TypeError):
                pass

        ok = not issues
        return ValidationResult(
            ok=ok,
            sql=final_sql,
            issues=issues,
            used_tables=used_tables,
            used_columns=used_columns,
        )
