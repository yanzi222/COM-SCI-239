"""
Fictional student record database and MCP tools for the Advisor Agent.
All data is synthetic; any resemblance to real persons is coincidental.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
from mcp.server.mcpserver import MCPServer

server = MCPServer("GradAdvisor-StudentDB")

# ---------------------------------------------------------------------------
# Fictional student records
# ---------------------------------------------------------------------------

@dataclass
class StudentRecord:
    student_id: str
    gpa: float
    units_completed: int
    standing: str           # good | warning | probation
    year_in_program: int
    extension_count_this_term: int
    advanced_to_candidacy: bool
    funding_category: str   # fellowship | ra | ta | self | unknown
    # Sensitive fields — never forwarded to Policy Checker
    _visa_status: str = field(repr=False, default="domestic")
    _immigration_hold: bool = field(repr=False, default=False)
    _financial_aid_amount: float = field(repr=False, default=0.0)


STUDENT_DB: dict[str, StudentRecord] = {
    "S001": StudentRecord(
        student_id="S001", gpa=3.8, units_completed=36, standing="good",
        year_in_program=2, extension_count_this_term=0,
        advanced_to_candidacy=False, funding_category="fellowship",
        _visa_status="domestic",
    ),
    "S002": StudentRecord(
        student_id="S002", gpa=3.1, units_completed=48, standing="warning",
        year_in_program=3, extension_count_this_term=1,
        advanced_to_candidacy=True, funding_category="ra",
        _visa_status="f1",
    ),
    "S003": StudentRecord(
        student_id="S003", gpa=2.6, units_completed=24, standing="probation",
        year_in_program=2, extension_count_this_term=2,
        advanced_to_candidacy=False, funding_category="self",
        _visa_status="domestic",
    ),
    "S004": StudentRecord(
        student_id="S004", gpa=3.9, units_completed=72, standing="good",
        year_in_program=5, extension_count_this_term=0,
        advanced_to_candidacy=True, funding_category="fellowship",
        _visa_status="domestic",
    ),
    "S005": StudentRecord(
        student_id="S005", gpa=3.5, units_completed=60, standing="good",
        year_in_program=6, extension_count_this_term=0,
        advanced_to_candidacy=True, funding_category="ta",
        _visa_status="j1",
    ),
}

COURSE_DB = {
    "CS229": {"name": "Machine Learning", "instructor": "Dr. Park", "capacity": 30, "enrolled": 28},
    "CS231N": {"name": "Convolutional Neural Networks", "instructor": "Dr. Lee", "capacity": 25, "enrolled": 25},
    "CS224N": {"name": "NLP with Deep Learning", "instructor": "Dr. Socher", "capacity": 20, "enrolled": 19},
    "STATS200": {"name": "Statistical Inference", "instructor": "Dr. Wu", "capacity": 40, "enrolled": 35},
}

# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@server.tool()
def get_student_record(student_id: str) -> dict:
    """
    Retrieve a student's academic record by student ID.
    Returns GPA, units completed, academic standing, year in program,
    extension count this term, candidacy status, and funding category.
    Sensitive fields (visa, financial aid) are NOT returned by this tool.
    """
    record = STUDENT_DB.get(student_id)
    if record is None:
        return {"error": f"No student found with ID {student_id}"}
    return {
        "student_id": record.student_id,
        "gpa": record.gpa,
        "units_completed": record.units_completed,
        "standing": record.standing,
        "year_in_program": record.year_in_program,
        "extension_count_this_term": record.extension_count_this_term,
        "advanced_to_candidacy": record.advanced_to_candidacy,
        "funding_category": record.funding_category,
    }


@server.tool()
def get_course_info(course_id: str) -> dict:
    """
    Retrieve course metadata: name, instructor, capacity, and current enrollment.
    """
    course = COURSE_DB.get(course_id.upper())
    if course is None:
        return {"error": f"Course {course_id} not found in catalog"}
    return {"course_id": course_id.upper(), **course}


@server.tool()
def check_candidacy(student_id: str) -> dict:
    """
    Return whether a student has been advanced to candidacy (passed qualifying exam).
    """
    record = STUDENT_DB.get(student_id)
    if record is None:
        return {"error": f"No student found with ID {student_id}"}
    return {
        "student_id": student_id,
        "advanced_to_candidacy": record.advanced_to_candidacy,
        "year_in_program": record.year_in_program,
    }


@server.tool()
def check_funding_status(student_id: str) -> dict:
    """
    Return the student's funding category only (fellowship, ra, ta, self, unknown).
    Does NOT return dollar amounts or financial aid package details.
    """
    record = STUDENT_DB.get(student_id)
    if record is None:
        return {"error": f"No student found with ID {student_id}"}
    return {
        "student_id": student_id,
        "funding_category": record.funding_category,
    }


if __name__ == "__main__":
    server.run()
