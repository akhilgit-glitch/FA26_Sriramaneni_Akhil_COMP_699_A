
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from itertools import combinations
from pathlib import Path

import pandas as pd
import streamlit as st


# ---------------------------------------------------------
# APPLICATION CONFIGURATION
# ---------------------------------------------------------

DB_PATH = Path(__file__).with_name("ruleguard.db")

OPERATORS = ["==", "!=", ">", ">=", "<", "<="]

DECISIONS = ["Approve", "Reject", "Review"]

VALUE_TYPES = ["number", "text", "boolean"]

ISSUE_STATUSES = ["Open", "Under review", "Resolved"]

st.set_page_config(
    page_title="RuleGuard",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

@contextmanager
def connect_db():
    connection = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")

    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_db():

    with connect_db() as connection:

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS rules (

                rule_id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                field TEXT NOT NULL,

                operator TEXT NOT NULL,

                value TEXT NOT NULL,

                value_type TEXT NOT NULL,

                decision TEXT NOT NULL,

                priority INTEGER NOT NULL DEFAULT 100,

                active INTEGER NOT NULL DEFAULT 1,

                created_at TEXT NOT NULL,

                updated_at TEXT
            );


            CREATE TABLE IF NOT EXISTS analysis_runs (

                analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,

                created_at TEXT NOT NULL,

                rule_count INTEGER NOT NULL,

                issue_count INTEGER NOT NULL,

                snapshot TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS issues (

                issue_id INTEGER PRIMARY KEY AUTOINCREMENT,

                analysis_id INTEGER NOT NULL,

                issue_type TEXT NOT NULL,

                rule_ids TEXT NOT NULL,

                explanation TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'Open',

                resolution_note TEXT NOT NULL DEFAULT '',

                updated_at TEXT,

                FOREIGN KEY (analysis_id)
                REFERENCES analysis_runs(analysis_id)
            );


            CREATE TABLE IF NOT EXISTS rule_audit (

                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,

                rule_id INTEGER,

                action TEXT NOT NULL,

                details TEXT NOT NULL,

                performed_at TEXT NOT NULL
            );


            CREATE INDEX IF NOT EXISTS idx_rules_active
            ON rules(active);


            CREATE INDEX IF NOT EXISTS idx_rules_field
            ON rules(field);


            CREATE INDEX IF NOT EXISTS idx_rules_priority
            ON rules(priority);


            CREATE INDEX IF NOT EXISTS idx_issues_analysis
            ON issues(analysis_id);


            CREATE INDEX IF NOT EXISTS idx_issues_status
            ON issues(status);


            CREATE INDEX IF NOT EXISTS idx_audit_rule
            ON rule_audit(rule_id);
            """
        )

        # Migration for databases created by the earlier version.
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(rules)"
            ).fetchall()
        }

        if "updated_at" not in columns:
            connection.execute(
                "ALTER TABLE rules ADD COLUMN updated_at TEXT"
            )

        issue_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(issues)"
            ).fetchall()
        }

        if "updated_at" not in issue_columns:
            connection.execute(
                "ALTER TABLE issues ADD COLUMN updated_at TEXT"
            )


# ---------------------------------------------------------
# COMMON UTILITIES
# ---------------------------------------------------------

def current_timestamp():

    return datetime.now().isoformat(timespec="seconds")


def record_audit(rule_id, action, details):

    with connect_db() as connection:

        connection.execute(
            """
            INSERT INTO rule_audit
            (rule_id, action, details, performed_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                rule_id,
                action,
                details,
                current_timestamp(),
            ),
        )


def get_audit_logs(limit=200):

    with connect_db() as connection:

        rows = connection.execute(
            """
            SELECT *
            FROM rule_audit
            ORDER BY audit_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]


# ---------------------------------------------------------
# DATABASE SEEDING
# ---------------------------------------------------------

def seed_rules():

    with connect_db() as connection:

        count = connection.execute(
            "SELECT COUNT(*) FROM rules"
        ).fetchone()[0]

        if count > 0:
            return

        now = current_timestamp()

        samples = [

            (
                "High value approval",
                "amount",
                ">=",
                "1000",
                "number",
                "Approve",
                10,
                1,
                now,
            ),

            (
                "High value rejection",
                "amount",
                ">=",
                "1500",
                "number",
                "Reject",
                20,
                1,
                now,
            ),

            (
                "Young customer review",
                "age",
                "<",
                "18",
                "number",
                "Review",
                30,
                1,
                now,
            ),

            (
                "Adult approval",
                "age",
                ">=",
                "18",
                "number",
                "Approve",
                40,
                1,
                now,
            ),

            (
                "Impossible age rule",
                "age",
                ">",
                "80",
                "number",
                "Reject",
                50,
                0,
                now,
            ),
        ]

        connection.executemany(
            """
            INSERT INTO rules
            (
                name,
                field,
                operator,
                value,
                value_type,
                decision,
                priority,
                active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            samples,
        )


# ---------------------------------------------------------
# RULE RETRIEVAL
# ---------------------------------------------------------

def get_rules(active_only=False):

    query = "SELECT * FROM rules"

    if active_only:
        query += " WHERE active = 1"

    query += " ORDER BY priority, rule_id"

    with connect_db() as connection:

        rows = connection.execute(query).fetchall()

        return [dict(row) for row in rows]


def get_rule(rule_id):

    with connect_db() as connection:

        row = connection.execute(
            "SELECT * FROM rules WHERE rule_id = ?",
            (int(rule_id),),
        ).fetchone()

        return dict(row) if row else None


# ---------------------------------------------------------
# VALUE PARSING AND VALIDATION
# ---------------------------------------------------------

def parse_value(value, value_type):

    if value_type == "number":

        try:
            parsed = float(value)
        except (ValueError, TypeError):
            raise ValueError("Enter a valid numeric value.")

        if not math.isfinite(parsed):
            raise ValueError("Numeric values must be finite.")

        return parsed

    if value_type == "boolean":

        normalized = str(value).strip().lower()

        if normalized not in ("true", "false"):
            raise ValueError(
                "Boolean values must be true or false."
            )

        return normalized == "true"

    if value_type == "text":

        return str(value)

    raise ValueError("Unsupported value type.")


def validate_rule(
    name,
    field,
    operator,
    value,
    value_type,
    decision,
    priority,
):

    name = str(name).strip()
    field = str(field).strip()

    if not name:
        raise ValueError("Please enter a rule name.")

    if not field:
        raise ValueError("Please enter a field name.")

    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_.]*",
        field,
    ):
        raise ValueError(
            "Field names must start with a letter or underscore "
            "and contain only letters, numbers, underscores, "
            "or periods."
        )

    if operator not in OPERATORS:
        raise ValueError("Choose a supported operator.")

    if decision not in DECISIONS:
        raise ValueError("Choose a supported decision.")

    if value_type not in VALUE_TYPES:
        raise ValueError("Choose a supported value type.")

    if value_type in ("text", "boolean"):

        if operator not in ("==", "!="):
            raise ValueError(
                "Text and Boolean fields support only == and !=."
            )

    parsed_value = parse_value(value, value_type)

    try:
        priority = int(priority)
    except (ValueError, TypeError):
        raise ValueError("Priority must be a whole number.")

    if priority < 1 or priority > 10000:
        raise ValueError(
            "Priority must be between 1 and 10000."
        )

    return parsed_value


def validate_field_type(field, value_type, exclude_rule_id=None):

    query = """
        SELECT rule_id, value_type
        FROM rules
        WHERE field = ?
    """

    params = [field]

    if exclude_rule_id is not None:

        query += " AND rule_id != ?"
        params.append(int(exclude_rule_id))

    with connect_db() as connection:

        rows = connection.execute(
            query,
            params,
        ).fetchall()

    for row in rows:

        if row["value_type"] != value_type:

            raise ValueError(
                f'The field "{field}" already uses the '
                f'{row["value_type"]} data type. '
                f'Use the same data type for this field.'
            )


# ---------------------------------------------------------
# RULE CREATION
# ---------------------------------------------------------

def add_rule(
    name,
    field,
    operator,
    value,
    value_type,
    decision,
    priority,
):

    validate_rule(
        name,
        field,
        operator,
        value,
        value_type,
        decision,
        priority,
    )

    validate_field_type(field.strip(), value_type)

    now = current_timestamp()

    with connect_db() as connection:

        cursor = connection.execute(
            """
            INSERT INTO rules
            (
                name,
                field,
                operator,
                value,
                value_type,
                decision,
                priority,
                active,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                name.strip(),
                field.strip(),
                operator,
                str(value),
                value_type,
                decision,
                int(priority),
                now,
                now,
            ),
        )

        rule_id = cursor.lastrowid

    record_audit(
        rule_id,
        "Created",
        f"Rule created: {name}",
    )

    return rule_id


# ---------------------------------------------------------
# RULE UPDATING
# ---------------------------------------------------------

def update_rule(
    rule_id,
    name,
    field,
    operator,
    value,
    value_type,
    decision,
    priority,
):

    validate_rule(
        name,
        field,
        operator,
        value,
        value_type,
        decision,
        priority,
    )

    validate_field_type(
        field.strip(),
        value_type,
        exclude_rule_id=rule_id,
    )

    old_rule = get_rule(rule_id)

    if not old_rule:
        raise ValueError("The selected rule no longer exists.")

    with connect_db() as connection:

        connection.execute(
            """
            UPDATE rules
            SET
                name = ?,
                field = ?,
                operator = ?,
                value = ?,
                value_type = ?,
                decision = ?,
                priority = ?,
                updated_at = ?
            WHERE rule_id = ?
            """,
            (
                name.strip(),
                field.strip(),
                operator,
                str(value),
                value_type,
                decision,
                int(priority),
                current_timestamp(),
                int(rule_id),
            ),
        )

    record_audit(
        rule_id,
        "Updated",
        (
            f'Rule "{old_rule["name"]}" updated. '
            f'New condition: {field} {operator} {value}. '
            f'New decision: {decision}.'
        ),
    )


# ---------------------------------------------------------
# RULE ACTIVATION AND DELETION
# ---------------------------------------------------------

def delete_rule(rule_id):

    rule = get_rule(rule_id)

    if not rule:
        raise ValueError("Rule not found.")

    with connect_db() as connection:

        connection.execute(
            "DELETE FROM rules WHERE rule_id = ?",
            (int(rule_id),),
        )

    record_audit(
        rule_id,
        "Deleted",
        f'Rule deleted: {rule["name"]}',
    )


def set_rule_active(rule_id, active):

    rule = get_rule(rule_id)

    if not rule:
        raise ValueError("Rule not found.")

    new_status = 1 if active else 0

    if rule["active"] == new_status:
        return

    with connect_db() as connection:

        connection.execute(
            """
            UPDATE rules
            SET active = ?, updated_at = ?
            WHERE rule_id = ?
            """,
            (
                new_status,
                current_timestamp(),
                int(rule_id),
            ),
        )

    record_audit(
        rule_id,
        "Activated" if active else "Deactivated",
        f'Rule "{rule["name"]}" status changed.',
    )


# ---------------------------------------------------------
# RULE COMPARISON
# ---------------------------------------------------------

def compare_values(left, operator, right):

    operations = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
    }

    if operator not in operations:
        raise ValueError(f"Unsupported operator: {operator}")

    return operations[operator](left, right)


def evaluate_rule(rule, input_values):

    field = rule["field"]

    if field not in input_values:
        return False

    left = parse_value(
        input_values[field],
        rule["value_type"],
    )

    right = parse_value(
        rule["value"],
        rule["value_type"],
    )

    return compare_values(
        left,
        rule["operator"],
        right,
    )


# ---------------------------------------------------------
# NUMERIC CONDITION ANALYSIS
# ---------------------------------------------------------

def interval_for_rule(rule):

    if rule["value_type"] != "number":
        return None

    value = float(rule["value"])
    operator = rule["operator"]

    lower = float("-inf")
    upper = float("inf")

    lower_inclusive = False
    upper_inclusive = False

    excluded = set()

    if operator == ">":

        lower = value

    elif operator == ">=":

        lower = value
        lower_inclusive = True

    elif operator == "<":

        upper = value

    elif operator == "<=":

        upper = value
        upper_inclusive = True

    elif operator == "==":

        lower = value
        upper = value

        lower_inclusive = True
        upper_inclusive = True

    elif operator == "!=":

        excluded.add(value)

    return {
        "lower": lower,
        "upper": upper,
        "lower_inclusive": lower_inclusive,
        "upper_inclusive": upper_inclusive,
        "excluded": excluded,
    }


def intervals_overlap(first, second):

    if first is None or second is None:
        return None

    lower = max(first["lower"], second["lower"])
    upper = min(first["upper"], second["upper"])

    if lower < upper:
        return True

    if lower > upper:
        return False

    # Both intervals meet at a single boundary.
    first_allows = (
        lower > first["lower"]
        or first["lower_inclusive"]
    ) and (
        lower < first["upper"]
        or first["upper_inclusive"]
    )

    second_allows = (
        lower > second["lower"]
        or second["lower_inclusive"]
    ) and (
        lower < second["upper"]
        or second["upper_inclusive"]
    )

    return (
        first_allows
        and second_allows
        and lower not in first["excluded"]
        and lower not in second["excluded"]
    )


# ---------------------------------------------------------
# TEXT AND BOOLEAN OVERLAP ANALYSIS
# ---------------------------------------------------------

def rules_overlap(first, second):

    if first["field"] != second["field"]:
        return False

    if first["value_type"] != second["value_type"]:
        return False

    value_type = first["value_type"]

    if value_type == "number":

        first_interval = interval_for_rule(first)
        second_interval = interval_for_rule(second)

        return intervals_overlap(
            first_interval,
            second_interval,
        )

    if value_type == "boolean":

        possible_values = [True, False]

        for value in possible_values:

            first_match = evaluate_rule(
                first,
                {first["field"]: value},
            )

            second_match = evaluate_rule(
                second,
                {second["field"]: value},
            )

            if first_match and second_match:
                return True

        return False

    if value_type == "text":

        first_value = str(first["value"])
        second_value = str(second["value"])

        first_operator = first["operator"]
        second_operator = second["operator"]

        if first_operator == "==" and second_operator == "==":
            return first_value == second_value

        if first_operator == "==" and second_operator == "!=":
            return first_value != second_value

        if first_operator == "!=" and second_operator == "==":
            return second_value != first_value

        # Two text exclusion conditions always have an
        # intersection because the text domain is not finite.
        return True

    return False


# ---------------------------------------------------------
# CONDITION FORMATTING
# ---------------------------------------------------------

def format_condition(rule):

    return (
        f'{rule["field"]} '
        f'{rule["operator"]} '
        f'{rule["value"]}'
    )


# ---------------------------------------------------------
# RULE CONFLICT ANALYSIS
# ---------------------------------------------------------

def analyze_rules(rules):

    active_rules = [
        rule for rule in rules
        if rule["active"]
    ]

    issues = []

    for first, second in combinations(active_rules, 2):

        if first["field"] != second["field"]:
            continue

        if first["value_type"] != second["value_type"]:
            continue

        overlap = rules_overlap(first, second)

        if not overlap:
            continue

        if first["decision"] != second["decision"]:

            issue_type = "Contradictory decisions"

            explanation = (
                f'Rules "{first["name"]}" and '
                f'"{second["name"]}" have overlapping conditions. '
                f'Condition 1: {format_condition(first)}. '
                f'Condition 2: {format_condition(second)}. '
                f'Both conditions can be satisfied by the same input, '
                f'but the rules return different decisions: '
                f'"{first["decision"]}" and "{second["decision"]}". '
                f'The priority order determines which decision '
                f'is applied during evaluation.'
            )

        else:

            issue_type = "Overlapping rules"

            explanation = (
                f'Rules "{first["name"]}" and '
                f'"{second["name"]}" have overlapping conditions. '
                f'Condition 1: {format_condition(first)}. '
                f'Condition 2: {format_condition(second)}. '
                f'Both rules return "{first["decision"]}". '
                f'Review the overlap to determine whether '
                f'both rules are required.'
            )

        issues.append(
            {
                "issue_type": issue_type,
                "rule_ids": [
                    first["rule_id"],
                    second["rule_id"],
                ],
                "explanation": explanation,
            }
        )

    return issues


# ---------------------------------------------------------
# ANALYSIS STORAGE
# ---------------------------------------------------------

def save_analysis(rules, issues):

    snapshot = json.dumps(
        rules,
        default=str,
    )

    active_count = len([
        rule for rule in rules
        if rule["active"]
    ])

    with connect_db() as connection:

        cursor = connection.execute(
            """
            INSERT INTO analysis_runs
            (
                created_at,
                rule_count,
                issue_count,
                snapshot
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                current_timestamp(),
                active_count,
                len(issues),
                snapshot,
            ),
        )

        analysis_id = cursor.lastrowid

        connection.executemany(
            """
            INSERT INTO issues
            (
                analysis_id,
                issue_type,
                rule_ids,
                explanation
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    analysis_id,
                    issue["issue_type"],
                    json.dumps(issue["rule_ids"]),
                    issue["explanation"],
                )
                for issue in issues
            ],
        )

    return analysis_id


# ---------------------------------------------------------
# ANALYSIS HISTORY
# ---------------------------------------------------------

def get_analyses():

    with connect_db() as connection:

        rows = connection.execute(
            """
            SELECT *
            FROM analysis_runs
            ORDER BY analysis_id DESC
            """
        ).fetchall()

        return [dict(row) for row in rows]


def get_analysis(analysis_id):

    with connect_db() as connection:

        row = connection.execute(
            """
            SELECT *
            FROM analysis_runs
            WHERE analysis_id = ?
            """,
            (int(analysis_id),),
        ).fetchone()

        return dict(row) if row else None


# ---------------------------------------------------------
# ISSUE RETRIEVAL AND MANAGEMENT
# ---------------------------------------------------------

def get_issues(analysis_id=None):

    query = """
        SELECT
            issues.*,
            analysis_runs.created_at AS analysis_date

        FROM issues

        JOIN analysis_runs
        ON issues.analysis_id = analysis_runs.analysis_id
    """

    params = ()

    if analysis_id is not None:

        query += " WHERE issues.analysis_id = ?"

        params = (int(analysis_id),)

    query += " ORDER BY issues.issue_id DESC"

    with connect_db() as connection:

        rows = connection.execute(
            query,
            params,
        ).fetchall()

        return [dict(row) for row in rows]


def update_issue(issue_id, status, note):

    if status not in ISSUE_STATUSES:
        raise ValueError("Choose a valid issue status.")

    with connect_db() as connection:

        cursor = connection.execute(
            """
            UPDATE issues
            SET
                status = ?,
                resolution_note = ?,
                updated_at = ?
            WHERE issue_id = ?
            """,
            (
                status,
                note.strip(),
                current_timestamp(),
                int(issue_id),
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError("Issue not found.")


# ---------------------------------------------------------
# BUSINESS RULE EVALUATION
# ---------------------------------------------------------

def evaluate_inputs(rules, input_values):

    matched = []

    ordered_rules = sorted(
        rules,
        key=lambda item: (
            item["priority"],
            item["rule_id"],
        ),
    )

    for rule in ordered_rules:

        if not rule["active"]:
            continue

        if evaluate_rule(rule, input_values):
            matched.append(rule)

    return matched


def get_effective_decision(matched_rules):

    if not matched_rules:
        return None

    ordered = sorted(
        matched_rules,
        key=lambda item: (
            item["priority"],
            item["rule_id"],
        ),
    )

    return ordered[0]


# ---------------------------------------------------------
# DISPLAY UTILITIES
# ---------------------------------------------------------

def display_rule(rule):

    return {
        "ID": rule["rule_id"],
        "Name": rule["name"],
        "Field": rule["field"],
        "Condition": format_condition(rule),
        "Type": rule["value_type"],
        "Decision": rule["decision"],
        "Priority": rule["priority"],
        "Active": (
            "Yes" if rule["active"] else "No"
        ),
        "Created": rule["created_at"],
        "Updated": rule["updated_at"] or "",
    }


def show_rules_table(rules):

    if rules:

        st.dataframe(
            pd.DataFrame(
                [display_rule(rule) for rule in rules]
            ),
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info("No rules are available.")


# ---------------------------------------------------------
# APPLICATION INITIALIZATION
# ---------------------------------------------------------

initialize_db()
seed_rules()

rules = get_rules()


# ---------------------------------------------------------
# SIDEBAR NAVIGATION
# ---------------------------------------------------------

st.title("RuleGuard")

st.caption(
    "Business Rule Conflict Detection and Resolution System"
)

st.write(
    "Manage business rules, identify overlapping conditions, "
    "evaluate business decisions, and maintain an auditable "
    "record of rule changes and issue resolutions."
)

page = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "Manage Rules",
        "Analyze Rules",
        "Test Rules",
        "Issue Review",
        "Analysis History",
        "Audit Trail",
    ],
)


# =========================================================
# DASHBOARD
# =========================================================

if page == "Dashboard":

    st.header("Dashboard")

    active_rules = [
        rule for rule in rules
        if rule["active"]
    ]

    inactive_rules = [
        rule for rule in rules
        if not rule["active"]
    ]

    analyses = get_analyses()
    issues = get_issues()

    open_issues = [
        issue for issue in issues
        if issue["status"] == "Open"
    ]

    review_issues = [
        issue for issue in issues
        if issue["status"] == "Under review"
    ]

    resolved_issues = [
        issue for issue in issues
        if issue["status"] == "Resolved"
    ]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Total rules",
        len(rules),
    )

    col2.metric(
        "Active rules",
        len(active_rules),
    )

    col3.metric(
        "Analysis runs",
        len(analyses),
    )

    col4.metric(
        "Unresolved issues",
        len(open_issues) + len(review_issues),
    )

    st.divider()

    st.subheader("Rule summary")

    col1, col2 = st.columns(2)

    with col1:

        st.write(
            f"Active rules: {len(active_rules)}"
        )

        st.write(
            f"Inactive rules: {len(inactive_rules)}"
        )

    with col2:

        st.write(
            f"Total saved rules: {len(rules)}"
        )

        st.write(
            f"Resolved issues: {len(resolved_issues)}"
        )

    st.divider()

    st.subheader("Latest analysis")

    if analyses:

        latest = analyses[0]

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Analysis ID",
            latest["analysis_id"],
        )

        col2.metric(
            "Rules analyzed",
            latest["rule_count"],
        )

        col3.metric(
            "Issues detected",
            latest["issue_count"],
        )

        st.write(
            f'Analysis date: {latest["created_at"]}'
        )

    else:

        st.info(
            "No analysis has been performed. "
            "Run an analysis to identify potential rule conflicts."
        )

    st.divider()

    st.subheader("Issue status")

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Open",
        len(open_issues),
    )

    col2.metric(
        "Under review",
        len(review_issues),
    )

    col3.metric(
        "Resolved",
        len(resolved_issues),
    )

    st.divider()

    st.subheader("Recently created rules")

    show_rules_table(
        sorted(
            rules,
            key=lambda item: item["rule_id"],
            reverse=True,
        )[:5]
    )


# =========================================================
# MANAGE RULES
# =========================================================

elif page == "Manage Rules":

    st.header("Manage Business Rules")

    st.subheader("Create a new rule")

    with st.form(
        "create_rule_form",
        clear_on_submit=True,
    ):

        col1, col2 = st.columns(2)

        with col1:

            name = st.text_input(
                "Rule name"
            )

            field = st.text_input(
                "Field name",
                value="amount",
            )

            value_type = st.selectbox(
                "Value type",
                VALUE_TYPES,
            )

        with col2:

            operator = st.selectbox(
                "Operator",
                OPERATORS,
            )

            value = st.text_input(
                "Condition value",
                value="1000",
            )

            decision = st.selectbox(
                "Expected decision",
                DECISIONS,
            )

        priority = st.number_input(
            "Priority (lower number runs first)",
            min_value=1,
            max_value=10000,
            value=100,
        )

        submitted = st.form_submit_button(
            "Save rule",
            type="primary",
        )

        if submitted:

            try:

                rule_id = add_rule(
                    name,
                    field,
                    operator,
                    value,
                    value_type,
                    decision,
                    priority,
                )

                st.success(
                    f"Rule #{rule_id} saved successfully."
                )

                st.rerun()

            except (
                ValueError,
                sqlite3.Error,
            ) as error:

                st.error(str(error))

    st.divider()

    st.subheader("Saved rules")

    rules = get_rules()

    show_rules_table(rules)

    if rules:

        st.divider()

        rule_options = {
            f'{rule["rule_id"]}: {rule["name"]}': rule
            for rule in rules
        }

        selected_label = st.selectbox(
            "Select a rule",
            list(rule_options.keys()),
        )

        selected_rule = rule_options[selected_label]

        tab1, tab2, tab3 = st.tabs(
            [
                "Edit rule",
                "Rule status",
                "Delete rule",
            ]
        )

        # -------------------------------------------------
        # EDIT RULE
        # -------------------------------------------------

        with tab1:

            st.subheader("Update selected rule")

            with st.form(
                f'edit_rule_{selected_rule["rule_id"]}'
            ):

                col1, col2 = st.columns(2)

                with col1:

                    edit_name = st.text_input(
                        "Rule name",
                        value=selected_rule["name"],
                    )

                    edit_field = st.text_input(
                        "Field name",
                        value=selected_rule["field"],
                    )

                    edit_type = st.selectbox(
                        "Value type",
                        VALUE_TYPES,
                        index=VALUE_TYPES.index(
                            selected_rule["value_type"]
                        ),
                    )

                with col2:

                    edit_operator = st.selectbox(
                        "Operator",
                        OPERATORS,
                        index=OPERATORS.index(
                            selected_rule["operator"]
                        ),
                    )

                    edit_value = st.text_input(
                        "Condition value",
                        value=selected_rule["value"],
                    )

                    edit_decision = st.selectbox(
                        "Expected decision",
                        DECISIONS,
                        index=DECISIONS.index(
                            selected_rule["decision"]
                        ),
                    )

                edit_priority = st.number_input(
                    "Priority",
                    min_value=1,
                    max_value=10000,
                    value=int(selected_rule["priority"]),
                )

                update_submitted = st.form_submit_button(
                    "Update rule",
                    type="primary",
                )

                if update_submitted:

                    try:

                        update_rule(
                            selected_rule["rule_id"],
                            edit_name,
                            edit_field,
                            edit_operator,
                            edit_value,
                            edit_type,
                            edit_decision,
                            edit_priority,
                        )

                        st.success(
                            "Rule updated successfully."
                        )

                        st.rerun()

                    except (
                        ValueError,
                        sqlite3.Error,
                    ) as error:

                        st.error(str(error))

        # -------------------------------------------------
        # RULE STATUS
        # -------------------------------------------------

        with tab2:

            st.subheader("Rule activation")

            st.write(
                f'Current status: '
                f'{"Active" if selected_rule["active"] else "Inactive"}'
            )

            new_active = st.checkbox(
                "Rule is active",
                value=bool(selected_rule["active"]),
                key=f'status_{selected_rule["rule_id"]}',
            )

            if st.button(
                "Update rule status",
                key=f'update_status_{selected_rule["rule_id"]}',
            ):

                try:

                    set_rule_active(
                        selected_rule["rule_id"],
                        new_active,
                    )

                    st.success(
                        "Rule status updated."
                    )

                    st.rerun()

                except (
                    ValueError,
                    sqlite3.Error,
                ) as error:

                    st.error(str(error))

        # -------------------------------------------------
        # DELETE RULE
        # -------------------------------------------------

        with tab3:

            st.subheader("Delete selected rule")

            st.warning(
                "Deleting a rule removes it from the current "
                "rule configuration. Previous analysis snapshots "
                "and associated issues remain available."
            )

            confirm_delete = st.checkbox(
                "I confirm that I want to delete this rule.",
                key=f'delete_{selected_rule["rule_id"]}',
            )

            if st.button(
                "Delete selected rule",
                type="primary",
                key=f'delete_button_{selected_rule["rule_id"]}',
            ):

                if confirm_delete:

                    try:

                        delete_rule(
                            selected_rule["rule_id"]
                        )

                        st.success(
                            "Rule deleted successfully."
                        )

                        st.rerun()

                    except (
                        ValueError,
                        sqlite3.Error,
                    ) as error:

                        st.error(str(error))

                else:

                    st.warning(
                        "Confirm the deletion before proceeding."
                    )


# =========================================================
# ANALYZE RULES
# =========================================================

elif page == "Analyze Rules":

    st.header("Analyze Business Rules")

    st.write(
        "The analysis evaluates active rules that use the same "
        "field and compatible data types. It identifies conditions "
        "that can match the same input and checks whether their "
        "decisions are consistent."
    )

    active_rules = get_rules(active_only=True)

    col1, col2 = st.columns(2)

    col1.metric(
        "Active rules",
        len(active_rules),
    )

    col2.metric(
        "Fields covered",
        len({
            rule["field"]
            for rule in active_rules
        }),
    )

    st.divider()

    st.subheader("Run conflict detection")

    if st.button(
        "Analyze active rules",
        type="primary",
    ):

        current_rules = get_rules()

        findings = analyze_rules(current_rules)

        analysis_id = save_analysis(
            current_rules,
            findings,
        )

        st.session_state["last_analysis_id"] = analysis_id

        st.session_state["last_findings"] = findings

        st.success(
            f"Analysis #{analysis_id} completed. "
            f"{len(findings)} potential issue(s) detected."
        )

    findings = st.session_state.get(
        "last_findings"
    )

    if findings is not None:

        st.divider()

        st.subheader("Analysis results")

        if not findings:

            st.success(
                "No overlapping or contradictory conditions "
                "were detected among the active rules."
            )

        else:

            contradictory = [
                issue for issue in findings
                if issue["issue_type"] == "Contradictory decisions"
            ]

            overlapping = [
                issue for issue in findings
                if issue["issue_type"] == "Overlapping rules"
            ]

            col1, col2 = st.columns(2)

            col1.metric(
                "Contradictory decisions",
                len(contradictory),
            )

            col2.metric(
                "Overlapping rules",
                len(overlapping),
            )

            for index, issue in enumerate(
                findings,
                start=1,
            ):

                with st.expander(
                    f'{index}. {issue["issue_type"]} '
                    f'— Rules {issue["rule_ids"]}'
                ):

                    st.write(
                        issue["explanation"]
                    )

                    st.write(
                        "Affected rule IDs: "
                        + ", ".join(
                            map(str, issue["rule_ids"])
                        )
                    )

                    if issue["issue_type"] == "Contradictory decisions":

                        st.warning(
                            "Different decisions are returned "
                            "for overlapping conditions. "
                            "Review the rule priority and business requirements."
                        )

                    else:

                        st.info(
                            "Both rules return the same decision, "
                            "but their conditions overlap."
                        )

    else:

        st.info(
            "Run an analysis to view conflict detection results."
        )


# =========================================================
# TEST RULES
# =========================================================

elif page == "Test Rules":

    st.header("Test Business Decisions")

    active_rules = get_rules(
        active_only=True
    )

    if not active_rules:

        st.info(
            "Create or activate rules before testing business decisions."
        )

    else:

        fields = sorted({
            rule["field"]
            for rule in active_rules
        })

        input_values = {}

        st.write(
            "Provide input values for the fields used by active rules."
        )

        st.divider()

        for field in fields:

            field_rules = [
                rule for rule in active_rules
                if rule["field"] == field
            ]

            value_type = field_rules[0]["value_type"]

            if value_type == "number":

                input_values[field] = st.number_input(
                    field,
                    value=0.0,
                    key=f"test_{field}",
                )

            elif value_type == "boolean":

                input_values[field] = st.selectbox(
                    field,
                    [False, True],
                    key=f"test_{field}",
                )

            else:

                input_values[field] = st.text_input(
                    field,
                    key=f"test_{field}",
                )

        st.divider()

        if st.button(
            "Evaluate input",
            type="primary",
        ):

            try:

                matched = evaluate_inputs(
                    active_rules,
                    input_values,
                )

                st.session_state["last_test_inputs"] = input_values

                st.session_state["last_test_matches"] = matched

                if matched:

                    st.subheader("Matched rules")

                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Rule ID": rule["rule_id"],
                                    "Rule": rule["name"],
                                    "Condition": format_condition(rule),
                                    "Decision": rule["decision"],
                                    "Priority": rule["priority"],
                                }
                                for rule in matched
                            ]
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

                    effective_rule = get_effective_decision(
                        matched
                    )

                    st.divider()

                    st.subheader("Effective business decision")

                    st.success(
                        f'Decision: {effective_rule["decision"]}'
                    )

                    st.write(
                        f'Applied rule: {effective_rule["name"]}'
                    )

                    st.write(
                        f'Rule ID: {effective_rule["rule_id"]}'
                    )

                    st.write(
                        f'Priority: {effective_rule["priority"]}'
                    )

                    decisions = {
                        rule["decision"]
                        for rule in matched
                    }

                    if len(decisions) > 1:

                        st.warning(
                            "Multiple matching rules return different "
                            "decisions. The rule with the lowest priority "
                            "number is selected as the effective decision. "
                            "Review the conflicting rules."
                        )

                    else:

                        st.info(
                            "All matched rules return the same decision."
                        )

                else:

                    st.info(
                        "No active rule matched the provided input values."
                    )

            except (
                ValueError,
                TypeError,
            ) as error:

                st.error(
                    f"Unable to evaluate the inputs: {error}"
                )


# =========================================================
# ISSUE REVIEW
# =========================================================

elif page == "Issue Review":

    st.header("Issue Review and Resolution")

    issues = get_issues()

    if not issues:

        st.info(
            "No saved issues are available. "
            "Run an analysis before reviewing issues."
        )

    else:

        open_count = sum(
            issue["status"] == "Open"
            for issue in issues
        )

        review_count = sum(
            issue["status"] == "Under review"
            for issue in issues
        )

        resolved_count = sum(
            issue["status"] == "Resolved"
            for issue in issues
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Open issues",
            open_count,
        )

        col2.metric(
            "Under review",
            review_count,
        )

        col3.metric(
            "Resolved issues",
            resolved_count,
        )

        st.divider()

        status_filter = st.selectbox(
            "Filter issues by status",
            [
                "All",
                *ISSUE_STATUSES,
            ],
        )

        filtered_issues = issues

        if status_filter != "All":

            filtered_issues = [
                issue for issue in issues
                if issue["status"] == status_filter
            ]

        if not filtered_issues:

            st.info(
                "No issues match the selected status."
            )

        for issue in filtered_issues:

            with st.expander(
                f'Issue #{issue["issue_id"]}: '
                f'{issue["issue_type"]} — {issue["status"]}'
            ):

                st.write(
                    f'Analysis run: #{issue["analysis_id"]}'
                )

                st.write(
                    f'Created: {issue["analysis_date"]}'
                )

                rule_ids = json.loads(
                    issue["rule_ids"]
                )

                st.write(
                    "Affected rule IDs: "
                    + ", ".join(
                        map(str, rule_ids)
                    )
                )

                st.write(
                    issue["explanation"]
                )

                st.divider()

                current_status = issue["status"]

                status = st.selectbox(
                    "Issue status",
                    ISSUE_STATUSES,
                    index=ISSUE_STATUSES.index(
                        current_status
                    ),
                    key=f'issue_status_{issue["issue_id"]}',
                )

                note = st.text_area(
                    "Resolution note",
                    value=issue["resolution_note"],
                    key=f'issue_note_{issue["issue_id"]}',
                )

                if st.button(
                    "Save issue update",
                    key=f'issue_save_{issue["issue_id"]}',
                ):

                    try:

                        update_issue(
                            issue["issue_id"],
                            status,
                            note,
                        )

                        st.success(
                            "Issue updated successfully."
                        )

                        st.rerun()

                    except (
                        ValueError,
                        sqlite3.Error,
                    ) as error:

                        st.error(str(error))


# =========================================================
# ANALYSIS HISTORY
# =========================================================

elif page == "Analysis History":

    st.header("Analysis History")

    analyses = get_analyses()

    if not analyses:

        st.info(
            "No analysis runs are available."
        )

    else:

        history_data = [
            {
                "Analysis ID": item["analysis_id"],
                "Date": item["created_at"],
                "Rules analyzed": item["rule_count"],
                "Issues found": item["issue_count"],
            }
            for item in analyses
        ]

        st.dataframe(
            pd.DataFrame(history_data),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        st.subheader("View historical analysis")

        selected_id = st.selectbox(
            "Select analysis ID",
            [
                item["analysis_id"]
                for item in analyses
            ],
        )

        selected_analysis = get_analysis(
            selected_id
        )

        if selected_analysis:

            st.write(
                f'Date: {selected_analysis["created_at"]}'
            )

            st.write(
                f'Rules analyzed: {selected_analysis["rule_count"]}'
            )

            st.write(
                f'Issues found: {selected_analysis["issue_count"]}'
            )

            st.divider()

            st.subheader("Historical rule configuration")

            historical_rules = json.loads(
                selected_analysis["snapshot"]
            )

            show_rules_table(
                historical_rules
            )

            st.divider()

            st.subheader("Historical issues")

            historical_issues = get_issues(
                selected_id
            )

            if historical_issues:

                for issue in historical_issues:

                    with st.expander(
                        f'Issue #{issue["issue_id"]}: '
                        f'{issue["issue_type"]}'
                    ):

                        st.write(
                            issue["explanation"]
                        )

                        st.write(
                            f'Status: {issue["status"]}'
                        )

                        if issue["resolution_note"]:

                            st.write(
                                "Resolution note: "
                                + issue["resolution_note"]
                            )

            else:

                st.info(
                    "No issues were recorded for this analysis."
                )


# =========================================================
# AUDIT TRAIL
# =========================================================

elif page == "Audit Trail":

    st.header("Rule Audit Trail")

    st.write(
        "The audit trail records changes made to business rules, "
        "including creation, modification, activation, deactivation, "
        "and deletion."
    )

    logs = get_audit_logs()

    if not logs:

        st.info(
            "No rule changes have been recorded."
        )

    else:

        st.metric(
            "Recorded rule activities",
            len(logs),
        )

        audit_data = [
            {
                "Audit ID": item["audit_id"],
                "Rule ID": item["rule_id"],
                "Action": item["action"],
                "Details": item["details"],
                "Performed at": item["performed_at"],
            }
            for item in logs
        ]

        st.dataframe(
            pd.DataFrame(audit_data),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        st.subheader("Filter audit records")

        actions = sorted({
            item["action"]
            for item in logs
        })

        selected_action = st.selectbox(
            "Action",
            ["All", *actions],
        )

        filtered_logs = logs

        if selected_action != "All":

            filtered_logs = [
                item for item in logs
                if item["action"] == selected_action
            ]

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Audit ID": item["audit_id"],
                        "Rule ID": item["rule_id"],
                        "Action": item["action"],
                        "Details": item["details"],
                        "Performed at": item["performed_at"],
                    }
                    for item in filtered_logs
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )


# ---------------------------------------------------------
# APPLICATION FOOTER
# ---------------------------------------------------------

st.sidebar.divider()

st.sidebar.caption(
    "RuleGuard Business Rule Management"
)

st.sidebar.caption(
    "Local SQLite database"
)
