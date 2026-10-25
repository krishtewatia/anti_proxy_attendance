"""The NIET CSE-DS 3rd-year, Semester V catalog and structure for the pilot.

This is data, not code: adding 2nd year or another branch later means adding
another catalog like this one (or entering it in the admin panel), not
changing the model.

Subject codes are the official ones used by the college ERP (Juno). Codes the
owner has not been able to give in full are marked INCOMPLETE; a code that
differs from the timetable sheet is marked MISMATCH. Both are shown as flags
in the admin panel until someone confirms them.

No teacher is assigned to anything here: faculty data is supplied later.
"""

TERM = {
    "term_id": "2026-27-ODD",
    "name": "Odd semester 2026-27",
    # Filled in by the administrator; needed before "attendance not entered"
    # can be counted.
    "start_date": None,
    "end_date": None,
}

BRANCH = {
    "code": "CSE-DS",
    "name": "Computer Science and Engineering (Data Science)",
    "department": "CSE-DS",
}

COHORT = {
    "cohort_id": "CSE-DS-Y3-2026-27-ODD",
    "branch": "CSE-DS",
    "year": 3,
    "semester": "V",
    "term_id": "2026-27-ODD",
    "name": "B.Tech CSE-DS, 3rd year, Semester V",
}

SECTIONS = ["A", "B", "C", "D"]

# key: a stable short name used inside the system (it never changes, so a
# code corrected later breaks nothing). short_names: how the timetable sheet
# writes the subject; the key itself always counts as one.
SUBJECTS = [
    {"key": "CN", "code": "BCSE0502A", "name": "Computer Networks", "type": "THEORY"},
    {"key": "DCC", "code": "BCSDS0501", "name": "DevOps and Cloud Computing", "type": "THEORY"},
    {"key": "PRED", "code": "BCSDS0516", "name": "Predictive Analytics", "type": "THEORY"},
    {
        "key": "AJAVA",
        "code": "BCSAI051...",
        "name": "Advance Java Programming",
        "type": "THEORY",
        "code_status": "INCOMPLETE",
        "code_note": "Only the start of the ERP code is known (BCSAI051...).",
    },
    {"key": "PROD", "code": "BCSDS0513", "name": "Product Analytics", "type": "THEORY"},
    {
        "key": "DP",
        "code": "BCSE051...",
        "name": "Design Pattern",
        "type": "THEORY",
        "code_status": "INCOMPLETE",
        "code_note": "Only the start of the ERP code is known (BCSE051...).",
    },
    {
        "key": "CN_LAB",
        "code": "BCSE0552A",
        "name": "Computer Networks Lab",
        "type": "LAB",
        "code_status": "MISMATCH",
        "code_note": "The ERP code BCSE0552A is used; the timetable sheet says BCSE0552B.",
    },
    {
        "key": "DCC_LAB",
        "code": "BCSDS0551",
        "name": "DevOps and Cloud Computing Lab",
        "type": "LAB",
    },
    {"key": "PRED_LAB", "code": "BCSDS0516P", "name": "Predictive Analytics Lab", "type": "LAB"},
    {
        "key": "AJAVA_LAB",
        "code": "BCSAI05...",
        "name": "Advance Java Lab",
        "type": "LAB",
        "code_status": "INCOMPLETE",
        "code_note": "Only the start of the ERP code is known (BCSAI05...).",
    },
    {
        "key": "DLDA",
        "code": "BCSML0555B",
        "name": "Deep Learning for Data Analytics",
        "type": "WORKSHOP",
    },
    {"key": "DT", "code": "BCSCC0501Y", "name": "Design Thinking-II", "type": "THEORY"},
    {
        "key": "RM",
        "code": "BCSCC0552",
        "name": "Research Methodology, Ethics and Writing",
        "type": "THEORY",
        # The timetable has only lab slots for it, written RM_LAB.
        "short_names": ["RM_LAB"],
    },
    {"key": "INTERN", "code": "BEC0559X", "name": "Internship-II", "type": "INTERNSHIP"},
    # Outside this system: kept in the catalog, never counted, never given slots.
    {
        "key": "PPE",
        "code": "BVAC0551",
        "name": "Professional Practice and Employability-I / ESD",
        "type": "THEORY",
        "tracked": False,
    },
    {"key": "MOOC", "code": "MOOC", "name": "MOOCs", "type": "OTHER", "tracked": False},
]

# Two independent kinds of year-wide groups: ELECTIVE sets and WORKSHOP sets.
# A student chooses one option and one group in each set, and the groups of
# different sets have nothing to do with each other (Predictive Analytics G1
# and Product Analytics G1 are different groups of students).
GROUP_SETS = [
    {
        "set_code": "DE-II",
        "kind": "ELECTIVE",
        "name": "Department Elective II",
        "options": [
            {
                "option_code": "PA",
                "name": "Predictive Analytics",
                "subject_keys": ["PRED", "PRED_LAB"],
                "groups": ["G1", "G2", "G3"],
            },
            {
                "option_code": "AJ",
                "name": "Advance Java Programming",
                "subject_keys": ["AJAVA", "AJAVA_LAB"],
                "groups": ["AJ"],
            },
        ],
    },
    {
        "set_code": "DE-III",
        "kind": "ELECTIVE",
        "name": "Department Elective III",
        "options": [
            {
                "option_code": "PROD",
                "name": "Product Analytics",
                "subject_keys": ["PROD"],
                "groups": ["G1", "G2", "G3"],
            },
            {
                "option_code": "DP",
                "name": "Design Pattern",
                "subject_keys": ["DP"],
                "groups": ["DP"],
            },
        ],
    },
    {
        "set_code": "DLDA",
        "kind": "WORKSHOP",
        "name": "Deep Learning for Data Analytics workshop groups",
        "options": [
            {
                "option_code": "DLDA",
                "name": "Deep Learning for Data Analytics",
                "subject_keys": ["DLDA"],
                "groups": ["DL1", "DL2", "DL3", "DL4"],
            }
        ],
    },
]

TIMETABLE_FILE = "ds3_sem5_timetable.csv"
