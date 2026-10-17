# RuleGuard: Business Rule Conflict Detection and Resolution System

## 1. Project Overview

RuleGuard is a Python-based application that helps organizations identify potential conflicts in business rules before using them in business processes.

Business rules may overlap, produce contradictory decisions, or contain conditions that cannot be satisfied. RuleGuard provides an interface for creating rules, analyzing conditions, testing decisions, reviewing issues, and tracking resolutions.

The application uses Streamlit for the user interface and SQLite for local data storage.

## 2. Project Objectives

- Create and manage structured business rules.
- Validate rule conditions and input values.
- Detect overlapping rules and contradictory decisions.
- Explain potential conflicts and identify affected rules.
- Test business decisions using custom input values.
- Store rules, analysis history, and issue statuses locally.
- Provide a dashboard for reviewing analysis results.

## 3. Technology Stack

- **Programming Language:** Python
- **User Interface:** Streamlit
- **Database:** SQLite
- **Data Format:** JSON
- **Testing Framework:** pytest (planned for automated test development)
- **Version Control:** Git and GitHub

## 4. Project Structure

```text
RuleGuard/
├── ruleguard_app.py
├── README.md
├── requirements.txt
├── ruleguard.db
└── .gitignore
```

The `ruleguard_app.py` file contains the application interface, rule-processing logic, database initialization, conflict detection, and issue management.

The `README.md` file documents the project and explains how to run it.

The `requirements.txt` file lists the required Python packages.

The `ruleguard.db` file is created automatically when the application runs. It stores rules, analysis results, and issues.

The `.gitignore` file prevents generated files and local environment files from being committed unnecessarily.

## 5. Prerequisites

Before running RuleGuard, install:

- Python 3.10 or a compatible newer version.
- pip, the Python package installer.
- Git, if you want to clone and maintain the repository.

Check your Python installation:

```bash
python --version
```

Check pip:

```bash
python -m pip --version
```

## 6. Installation Instructions

Clone the repository:

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
```

Open the project folder:

```bash
cd RuleGuard
```

Install the required package:

```bash
python -m pip install -r requirements.txt
```

If `requirements.txt` has not yet been created, install Streamlit directly:

```bash
python -m pip install streamlit
```

## 7. Running the Application

Start RuleGuard using:

```bash
python -m streamlit run ruleguard_app.py
```

Streamlit will start a local web server and display the application URL in the terminal. Open that URL in your browser to use the application.

No external API keys, cloud services, or database server are required.

## 8. Application Features

### Dashboard

Displays the total number of rules, active rules, analysis runs, and unresolved issues.

### Manage Rules

Allows users to create rules, select conditions and operators, define expected decisions, set priorities, and activate or delete rules.

### Analyze Rules

Compares active rules that use the same field and compatible value types. It identifies potential overlaps and contradictory decisions and displays explanations.

### Test Rules

Allows users to enter sample values and evaluate which active rules match those inputs. The application displays the matching rules and their decisions.

### Issue Review

Allows users to review detected issues, update their statuses, and record resolution notes.

### Analysis History

Displays previous analysis runs and their recorded findings.

## 9. Database and Configuration

RuleGuard uses SQLite for local storage. The database is initialized automatically when the application starts.

The database stores business rules, analysis runs, and issues. The application creates the necessary tables if they do not already exist.

The database filename is:

```text
ruleguard.db
```

The application does not require a separate database installation or configuration file.

Keep a backup of the database if you need to preserve locally created rules and analysis history.

## 10. Preliminary Implementation

The preliminary implementation demonstrates the main technical components of the proposed system:

- Structured rule creation and validation.
- Rule evaluation using supported comparison operators.
- Detection of potential overlapping conditions.
- Identification of contradictory decisions.
- SQLite database initialization and persistence.
- Generation and storage of analysis findings.
- Test-case evaluation using user-provided inputs.
- Issue status management and analysis history.

The initial implementation focuses on individual conditions. Complete unreachable-rule detection and comprehensive analysis of complex combinations of AND/OR conditions remain future improvements.

## 11. Testing and Evaluation

The completed system will be evaluated through the following activities:

1. Unit testing of rule validation and condition evaluation.
2. Conflict-detection testing using overlapping and contradictory rules.
3. Database testing to confirm that rules and issue statuses persist after restarting the application.
4. Workflow testing covering rule creation, analysis, testing, and issue resolution.
5. Accuracy testing using at least 100 manually verified test cases.
6. Performance testing to measure whether 500 representative rules can be analyzed within five seconds.
7. Usability testing to assess whether a new user can complete the main workflow within ten minutes.

Test results, screenshots, execution times, and failed cases will be recorded as evidence. Targets will be considered achieved only after the relevant tests have been executed successfully.

## 12. Development Schedule

- October 17–23, 2026: Requirements and architecture.
- October 24–30, 2026: Technical proof of concept.
- October 31–November 8, 2026: Core implementation.
- November 9–15, 2026: Component integration.
- November 16–20, 2026: Minimum viable product.
- November 21–27, 2026: Testing and evaluation.
- November 28–December 2, 2026: Refinement.
- December 3–5, 2026: Documentation.
- December 6–7, 2026: Final verification.
- December 8, 2026: Final submission and presentation.

## 13. Limitations

The current version is a preliminary proof of concept. It supports individual conditions and a defined set of comparison operators. Some complex conditions may require manual review.

The application does not automatically modify business policies, connect to production systems, provide enterprise authentication, or support multiple users working together.

Further development will expand the analysis algorithms, improve automated testing, and strengthen the evaluation of unreachable rules.

## 14. Future Improvements

- Support more complex combinations of AND and OR conditions.
- Improve unreachable-rule detection.
- Add rule editing and version comparison.
- Expand automated unit and integration tests.
- Improve reporting and export options.
- Add more detailed test coverage and performance measurements.

## 15. Security and Repository Practices

Do not commit passwords, API keys, credentials, or `.env` files containing secrets.

Keep generated databases and temporary files out of the repository when they contain local or unnecessary data. Include only files needed to understand, install, run, and evaluate the project.

Commit changes regularly so that the repository records the project's development progress.

## 16. References

Python Software Foundation. (n.d.). *Python documentation*. https://docs.python.org/3/

Streamlit. (n.d.). *Streamlit documentation*. https://docs.streamlit.io/

SQLite. (n.d.). *SQLite documentation*. https://www.sqlite.org/docs.html

pytest. (n.d.). *pytest documentation*. https://docs.pytest.org/en/stable/
