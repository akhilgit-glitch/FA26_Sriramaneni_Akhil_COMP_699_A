import json
import sqlite3
from datetime import datetime
from itertools import combinations

import streamlit as st

DB_PATH = "ruleguard.db"
OPERATORS = ["==", "!=", ">", ">=", "<", "<="]
DECISIONS = ["Approve", "Reject", "Review"]


def connect_db():
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_db():
    # I create the local tables that keep rules, analysis runs, and issues.
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
                created_at TEXT NOT NULL
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
                FOREIGN KEY (analysis_id) REFERENCES analysis_runs(analysis_id)
            );
            """
        )


def seed_rules():
    with connect_db() as connection:
        count = connection.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
        if count:
            return
        now = datetime.now().isoformat(timespec="seconds")
        samples = [
            ("High value approval", "amount", ">=", "1000", "number", "Approve", 10, 1, now),
            ("High value rejection", "amount", ">=", "1500", "number", "Reject", 20, 1, now),
            ("Young customer review", "age", "<", "18", "number", "Review", 30, 1, now),
            ("Adult approval", "age", ">=", "18", "number", "Approve", 40, 1, now),
            ("Impossible age rule", "age", ">", "80", "number", "Reject", 50, 0, now),
        ]
        connection.executemany(
            """INSERT INTO rules
            (name, field, operator, value, value_type, decision, priority, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            samples,
        )


def get_rules(active_only=False):
    query = "SELECT * FROM rules"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY priority, rule_id"
    with connect_db() as connection:
        return [dict(row) for row in connection.execute(query).fetchall()]


def parse_value(value, value_type):
    if value_type == "number":
        return float(value)
    if value_type == "boolean":
        normalized = str(value).strip().lower()
        if normalized not in ("true", "false"):
            raise ValueError("Boolean values must be true or false.")
        return normalized == "true"
    return str(value)


def validate_rule(name, field, operator, value, value_type, decision):
    if not name.strip():
        raise ValueError("Please enter a rule name.")
    if not field.strip():
        raise ValueError("Please enter a field name.")
    if operator not in OPERATORS:
        raise ValueError("Choose a supported operator.")
    if decision not in DECISIONS:
        raise ValueError("Choose a supported decision.")
    parsed = parse_value(value, value_type)
    if value_type == "text" and operator not in ("==", "!="):
        raise ValueError("Text fields support only == and !=.")
    if value_type == "boolean" and operator not in ("==", "!="):
        raise ValueError("Boolean fields support only == and !=.")
    return parsed


def add_rule(name, field, operator, value, value_type, decision, priority):
    validate_rule(name, field, operator, value, value_type, decision)
    with connect_db() as connection:
        connection.execute(
            """INSERT INTO rules
            (name, field, operator, value, value_type, decision, priority, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                name.strip(),
                field.strip(),
                operator,
                str(value),
                value_type,
                decision,
                int(priority),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def delete_rule(rule_id):
    with connect_db() as connection:
        connection.execute("DELETE FROM rules WHERE rule_id = ?", (int(rule_id),))


def set_rule_active(rule_id, active):
    with connect_db() as connection:
        connection.execute(
            "UPDATE rules SET active = ? WHERE rule_id = ?",
            (1 if active else 0, int(rule_id)),
        )


def compare_values(left, operator, right):
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    raise ValueError(f"Unsupported operator: {operator}")


def evaluate_rule(rule, input_values):
    field = rule["field"]
    if field not in input_values:
        return False
    left = parse_value(input_values[field], rule["value_type"])
    right = parse_value(rule["value"], rule["value_type"])
    return compare_values(left, rule["operator"], right)


def interval_for_rule(rule):
    if rule["value_type"] != "number":
        return None
    value = float(rule["value"])
    operator = rule["operator"]
    lower = float("-inf")
    upper = float("inf")
    lower_inclusive = False
    upper_inclusive = False

    if operator == ">":
        lower = value
    elif operator == ">=":
        lower, lower_inclusive = value, True
    elif operator == "<":
        upper = value
    elif operator == "<=":
        upper, upper_inclusive = value, True
    elif operator == "==":
        lower, upper = value, value
        lower_inclusive, upper_inclusive = True, True
    elif operator == "!=":
        return {"excluded": value}
    return {
        "lower": lower,
        "upper": upper,
        "lower_inclusive": lower_inclusive,
        "upper_inclusive": upper_inclusive,
    }


def intervals_overlap(first, second):
    if first is None or second is None:
        return None
    if "excluded" in first or "excluded" in second:
        return None

    lower = max(first["lower"], second["lower"])
    upper = min(first["upper"], second["upper"])
    if lower < upper:
        return True
    if lower > upper:
        return False

    first_allows = (
        (lower > first["lower"] or first["lower_inclusive"])
        and (lower < first["upper"] or first["upper_inclusive"])
    )
    second_allows = (
        (lower > second["lower"] or second["lower_inclusive"])
        and (lower < second["upper"] or second["upper_inclusive"])
    )
    return first_allows and second_allows


def format_condition(rule):
    return f'{rule["field"]} {rule["operator"]} {rule["value"]}'


def analyze_rules(rules):
    # I compare active rules that use the same field and compatible value types.
    active_rules = [rule for rule in rules if rule["active"]]
    issues = []

    for first, second in combinations(active_rules, 2):
        if first["field"] != second["field"]:
            continue
        if first["value_type"] != second["value_type"]:
            continue

        overlap = intervals_overlap(
            interval_for_rule(first), interval_for_rule(second)
        )
        if overlap is False:
            continue

        if overlap is None:
            try:
                same_value = parse_value(first["value"], first["value_type"]) == parse_value(
                    second["value"], second["value_type"]
                )
                if first["operator"] in ("==", "!=") and second["operator"] in ("==", "!="):
                    sample_values = [first["value"], second["value"]]
                    overlap = any(
                        evaluate_rule(first, {first["field"]: value})
                        and evaluate_rule(second, {second["field"]: value})
                        for value in sample_values
                    )
                else:
                    overlap = True
            except (ValueError, TypeError):
                overlap = None

        if overlap is False:
            continue

        if first["decision"] != second["decision"]:
            issue_type = "Contradictory decisions"
            explanation = (
                f'Rules "{first["name"]}" and "{second["name"]}" may both match '
                f'when {format_condition(first)} and {format_condition(second)} '
                f'are satisfied, but they return "{first["decision"]}" and '
                f'"{second["decision"]}".'
            )
        else:
            issue_type = "Overlapping rules"
            explanation = (
                f'Rules "{first["name"]}" and "{second["name"]}" may both match '
                f'when {format_condition(first)} and {format_condition(second)} '
                f'are satisfied. Both return "{first["decision"]}".'
            )

        if overlap is None:
            explanation += " The overlap needs manual review because this condition combination is not fully analyzed."
        issues.append(
            {
                "issue_type": issue_type,
                "rule_ids": [first["rule_id"], second["rule_id"]],
                "explanation": explanation,
            }
        )

    return issues


def save_analysis(rules, issues):
    snapshot = json.dumps(rules)
    with connect_db() as connection:
        cursor = connection.execute(
            """INSERT INTO analysis_runs (created_at, rule_count, issue_count, snapshot)
            VALUES (?, ?, ?, ?)""",
            (
                datetime.now().isoformat(timespec="seconds"),
                len([rule for rule in rules if rule["active"]]),
                len(issues),
                snapshot,
            ),
        )
        analysis_id = cursor.lastrowid
        connection.executemany(
            """INSERT INTO issues (analysis_id, issue_type, rule_ids, explanation)
            VALUES (?, ?, ?, ?)""",
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


def get_analyses():
    with connect_db() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM analysis_runs ORDER BY analysis_id DESC"
            ).fetchall()
        ]


def get_issues(analysis_id=None):
    query = """
        SELECT issues.*, analysis_runs.created_at AS analysis_date
        FROM issues JOIN analysis_runs
        ON issues.analysis_id = analysis_runs.analysis_id
    """
    params = ()
    if analysis_id is not None:
        query += " WHERE issues.analysis_id = ?"
        params = (int(analysis_id),)
    query += " ORDER BY issues.issue_id DESC"
    with connect_db() as connection:
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def update_issue(issue_id, status, note):
    with connect_db() as connection:
        connection.execute(
            "UPDATE issues SET status = ?, resolution_note = ? WHERE issue_id = ?",
            (status, note, int(issue_id)),
        )


def evaluate_inputs(rules, input_values):
    # I evaluate rules in priority order so the results are easy to review.
    matched = []
    for rule in sorted(rules, key=lambda item: (item["priority"], item["rule_id"])):
        if rule["active"] and evaluate_rule(rule, input_values):
            matched.append(rule)
    return matched


def display_rule(rule):
    return {
        "ID": rule["rule_id"],
        "Name": rule["name"],
        "Condition": format_condition(rule),
        "Decision": rule["decision"],
        "Priority": rule["priority"],
        "Active": "Yes" if rule["active"] else "No",
    }


# I keep the full proof of concept in one Streamlit file.
st.set_page_config(page_title="RuleGuard", page_icon=None, layout="wide")
initialize_db()
seed_rules()

st.title("RuleGuard")
st.caption("Business Rule Conflict Detection and Resolution System")
st.write(
    "I built this proof of concept to manage structured business rules, "
    "detect possible conflicts, test decisions, and track issues locally."
)

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Manage Rules", "Analyze Rules", "Test Rules", "Issue Review", "Analysis History"],
)

rules = get_rules()

if page == "Dashboard":
    active_rules = [rule for rule in rules if rule["active"]]
    analyses = get_analyses()
    issues = get_issues()
    open_issues = [issue for issue in issues if issue["status"] != "Resolved"]
    resolved_issues = [issue for issue in issues if issue["status"] == "Resolved"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total rules", len(rules))
    col2.metric("Active rules", len(active_rules))
    col3.metric("Analysis runs", len(analyses))
    col4.metric("Open issues", len(open_issues))

    st.subheader("Recent analysis")
    if analyses:
        latest = analyses[0]
        st.write(f'Latest run: #{latest["analysis_id"]} on {latest["created_at"]}')
        st.write(f'Rules analyzed: {latest["rule_count"]}')
        st.write(f'Issues detected: {latest["issue_count"]}')
    else:
        st.info("No analysis has been run yet. Open Analyze Rules to begin.")

    st.subheader("Issue status")
    st.write(f"Open or under review: {len(open_issues)}")
    st.write(f"Resolved: {len(resolved_issues)}")

elif page == "Manage Rules":
    st.subheader("Create a rule")
    with st.form("create_rule_form", clear_on_submit=True):
        name = st.text_input("Rule name")
        field = st.text_input("Field name", value="amount")
        value_type = st.selectbox("Value type", ["number", "text", "boolean"])
        operator = st.selectbox("Operator", OPERATORS)
        value = st.text_input("Condition value", value="1000")
        decision = st.selectbox("Expected decision", DECISIONS)
        priority = st.number_input("Priority (lower number runs first)", min_value=1, max_value=10000, value=100)
        submitted = st.form_submit_button("Save rule")
        if submitted:
            try:
                add_rule(name, field, operator, value, value_type, decision, priority)
                st.success("Rule saved.")
                st.rerun()
            except (ValueError, sqlite3.Error) as error:
                st.error(str(error))

    st.subheader("Saved rules")
    if rules:
        st.dataframe([display_rule(rule) for rule in rules], use_container_width=True, hide_index=True)
        rule_options = {
            f'{rule["rule_id"]}: {rule["name"]}': rule for rule in rules
        }
        selected_label = st.selectbox("Select a rule to manage", list(rule_options))
        selected_rule = rule_options[selected_label]
        col1, col2 = st.columns(2)
        with col1:
            new_active = st.checkbox(
                "Rule is active",
                value=bool(selected_rule["active"]),
                key=f'active_{selected_rule["rule_id"]}',
            )
            if st.button("Update active status"):
                set_rule_active(selected_rule["rule_id"], new_active)
                st.success("Rule status updated.")
                st.rerun()
        with col2:
            confirm_delete = st.checkbox(
                "Confirm rule deletion",
                key=f'delete_confirm_{selected_rule["rule_id"]}',
            )
            if st.button("Delete selected rule"):
                if confirm_delete:
                    delete_rule(selected_rule["rule_id"])
                    st.success("Rule deleted.")
                    st.rerun()
                else:
                    st.warning("Select the confirmation checkbox first.")
    else:
        st.info("No rules have been created.")

elif page == "Analyze Rules":
    st.subheader("Run conflict detection")
    st.write("The analysis compares active rules that use the same field and compatible value types.")
    if st.button("Analyze active rules", type="primary"):
        current_rules = get_rules()
        findings = analyze_rules(current_rules)
        analysis_id = save_analysis(current_rules, findings)
        st.session_state["last_analysis_id"] = analysis_id
        st.session_state["last_findings"] = findings
        st.success(f"Analysis #{analysis_id} completed. {len(findings)} potential issue(s) detected.")

    findings = st.session_state.get("last_findings")
    if findings is not None:
        st.subheader("Analysis results")
        if not findings:
            st.success("No potential overlaps or contradictory decisions were detected.")
        else:
            for index, issue in enumerate(findings, start=1):
                with st.expander(f'{index}. {issue["issue_type"]} — Rules {issue["rule_ids"]}'):
                    st.write(issue["explanation"])
                    st.write("Affected rule IDs: " + ", ".join(map(str, issue["rule_ids"])))
    else:
        st.info("Run an analysis to view results.")

elif page == "Test Rules":
    st.subheader("Test a business decision")
    active_rules = get_rules(active_only=True)
    if not active_rules:
        st.info("Create or activate rules before testing.")
    else:
        fields = sorted({rule["field"] for rule in active_rules})
        input_values = {}
        st.write("Enter values for the fields used by your active rules.")
        for field in fields:
            field_rules = [rule for rule in active_rules if rule["field"] == field]
            value_type = field_rules[0]["value_type"]
            if value_type == "number":
                input_values[field] = st.number_input(field, value=0.0, key=f"test_{field}")
            elif value_type == "boolean":
                input_values[field] = st.selectbox(field, [False, True], key=f"test_{field}")
            else:
                input_values[field] = st.text_input(field, key=f"test_{field}")

        if st.button("Evaluate input", type="primary"):
            try:
                matched = evaluate_inputs(active_rules, input_values)
                if matched:
                    st.subheader("Matched rules")
                    st.dataframe(
                        [
                            {
                                "Rule ID": rule["rule_id"],
                                "Rule": rule["name"],
                                "Condition": format_condition(rule),
                                "Decision": rule["decision"],
                                "Priority": rule["priority"],
                            }
                            for rule in matched
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                    decisions = sorted({rule["decision"] for rule in matched})
                    if len(decisions) > 1:
                        st.warning("The matched rules return different decisions. Review their priority and conditions.")
                    else:
                        st.write(f"Decision returned by matched rules: {decisions[0]}")
                else:
                    st.info("No active rule matched these input values.")
            except (ValueError, TypeError) as error:
                st.error(f"Unable to evaluate these inputs: {error}")

elif page == "Issue Review":
    st.subheader("Review detected issues")
    issues = get_issues()
    if not issues:
        st.info("No saved issues are available. Run an analysis first.")
    else:
        for issue in issues:
            with st.expander(
                f'Issue #{issue["issue_id"]}: {issue["issue_type"]} — {issue["status"]}'
            ):
                st.write(f'Analysis run: #{issue["analysis_id"]}')
                st.write(f'Created: {issue["analysis_date"]}')
                st.write("Affected rule IDs: " + ", ".join(map(str, json.loads(issue["rule_ids"]))))
                st.write(issue["explanation"])
                status = st.selectbox(
                    "Status",
                    ["Open", "Under review", "Resolved"],
                    index=["Open", "Under review", "Resolved"].index(issue["status"]),
                    key=f'issue_status_{issue["issue_id"]}',
                )
                note = st.text_area(
                    "Resolution note",
                    value=issue["resolution_note"],
                    key=f'issue_note_{issue["issue_id"]}',
                )
                if st.button("Save issue update", key=f'issue_save_{issue["issue_id"]}'):
                    update_issue(issue["issue_id"], status, note)
                    st.success("Issue updated.")
                    st.rerun()

elif page == "Analysis History":
    st.subheader("Analysis history")
    analyses = get_analyses()
    if not analyses:
        st.info("No analysis runs are available.")
    else:
        st.dataframe(
            [
                {
                    "Analysis ID": item["analysis_id"],
                    "Date": item["created_at"],
                    "Rules analyzed": item["rule_count"],
                    "Issues found": item["issue_count"],
                }
                for item in analyses
            ],
            use_container_width=True,
            hide_index=True,
        )
        selected_id = st.selectbox(
            "View issues from analysis",
            [item["analysis_id"] for item in analyses],
        )
        historical_issues = get_issues(selected_id)
        if historical_issues:
            for issue in historical_issues:
                st.markdown(f'**Issue #{issue["issue_id"]}: {issue["issue_type"]}**')
                st.write(issue["explanation"])
                st.write(f'Status: {issue["status"]}')
        else:
            st.write("No issues were recorded for this analysis.")
