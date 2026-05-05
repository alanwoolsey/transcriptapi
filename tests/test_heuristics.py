from app.services.extractors import HeuristicJudge
from app.services.heuristics import TranscriptHeuristicParser


SAMPLE_COLLEGE_TEXT = """
Example State University
Student Name: Jane Smith
Student ID: 123456
Fall 2024
ENG101 English Composition 3 A
MATH120 College Algebra 3 B+
HIST110 US History 3 A-
Cumulative GPA 3.76
Credits Attempted 62
Credits Earned 59
""".strip()


def test_heuristic_assessment_accepts_good_text():
    judge = HeuristicJudge()
    assessment = judge.assess(SAMPLE_COLLEGE_TEXT)
    assert assessment.acceptable is True
    assert assessment.score >= 0.65


def test_parser_extracts_student_summary_and_courses():
    parser = TranscriptHeuristicParser()
    doc_type = parser.detect_document_type(SAMPLE_COLLEGE_TEXT)
    parsed = parser.parse(SAMPLE_COLLEGE_TEXT, doc_type)

    assert parsed["document_type"] == "college_transcript"
    assert parsed["student"]["name"] == "Jane Smith"
    assert parsed["student"]["student_id"] == "123456"
    assert parsed["academic_summary"]["gpa"] == 3.76
    assert parsed["academic_summary"]["total_credits_attempted"] == 62.0
    assert parsed["academic_summary"]["total_credits_earned"] == 59.0
    assert len(parsed["terms"]) == 1
    assert len(parsed["terms"][0]["courses"]) == 3
    assert parsed["course_confidence_summary"]["average"] >= 0.8
    assert parsed["terms"][0]["courses"][0]["confidence_score"] >= 0.8


def test_parser_merges_split_institution_name_fragments():
    parser = TranscriptHeuristicParser()
    text = """
TR
ANSCRIPT OF
ACADEMIC RECORD
Issued To:
STUDENT
OR
EGON STATE UNIVERSITY
Fall 2024
ENG101 English Composition 3 A
""".strip()

    parsed = parser.parse(text, "college_transcript")

    assert parsed["institutions"][0]["name"] == "OREGON STATE UNIVERSITY"


def test_parser_handles_phoenix_line_based_course_rows():
    parser = TranscriptHeuristicParser()
    text = """
    UNIVERSITY OF PHOENIX
    Mo/Year Course ID Course Title Grade Credits Credits Quality Rep
    05/2015 GEN/127 University Studies for Success C+ 3.00 3.00 6.99
    06/2015 ENG/147 University Writing Essentials C- 3.00 3.00 5.01
    08/2015 HUM/115 Critical Thinking in Everyday Life C+ 3.00 3.00 6.99
    09/2015 CJS/201 Introduction to Criminal Justice C+ 3.00 3.00 6.99
    12/2015 CJS/205 Composition for Communication in the Criminal Justice System W 0.00 0.00 0.00
    01/2016 IT/200 Digital Skills for the 21st Century W 0.00 0.00 0.00
    UOPX Cumulative: 2.17 12.00 12.00 25.98
    Record of: ANDRAYUS J. FLUELLEN Student Number: 9054839836
    Birthdate: 10/12/1986
    """.strip()

    parsed = parser.parse(text, "college_transcript")

    assert parsed["student"]["name"] == "Andrayus J. Fluellen"
    assert parsed["student"]["student_id"] == "9054839836"
    assert parsed["academic_summary"]["gpa"] == 2.17
    assert parsed["academic_summary"]["total_credits_earned"] == 12.0
    courses = [course for term in parsed["terms"] for course in term["courses"]]
    assert len(courses) == 6
    by_code = {course["course_code"]: course for course in courses}
    assert by_code["ENG147"]["grade"] == "C-"
    assert by_code["CJS201"]["course_title"] == "Introduction to Criminal Justice"
    assert by_code["IT200"]["grade"] == "W"


def test_parser_handles_milwaukee_area_technical_college_ocr_rows():
    parser = TranscriptHeuristicParser()
    text = """
    MILWAUKEE AREA TECHNICAL COLLEGE
    TRANSCRIPT
    18. Yvonne Kelsey
    ID Number: 0731552
    Birth Date: 08/23/80
    AODA
    109
    Drug Use and Abuse
    A
    3.00
    3.00
    12.00000
    08/24/15-12/14/15
    GENREA 105
    Intro Reading & Study Skills
    A
    3.00
    3.00
    12.00000
    08/25/15-12/17/15
    HUMSVC 127
    Disabity & Helping Profession B+
    3.00
    3.00 9.75000 08/26/15-12/16/15
    Term FA2016
    Totals:
    COMPSW 106
    Intro to MS Office 2013
    A
    3.00
    3.00 12.00000 01/19/16-05/17/16
    Group Work Skills
    B
    3.00
    3.00
    9.00000
    08/28/17-12/18/17
    HUMSVC 103
    Term FA2018
    TOTALS: CRED ATT 54.00 CRED. CPT 46.00 GRADE.PTS 123.0000 GPA 2.2778
    """.strip()

    parsed = parser.parse(text, "college_transcript")

    assert parsed["student"]["name"] == "Yvonne Kelsey"
    assert parsed["student"]["student_id"] == "0731552"
    assert parsed["academic_summary"]["gpa"] == 2.2778
    courses = [course for term in parsed["terms"] for course in term["courses"]]
    assert len(courses) == 5
    by_code = {course["course_code"]: course for course in courses}
    assert by_code["AODA109"]["course_title"] == "Drug Use and Abuse"
    assert by_code["GENREA105"]["grade"] == "A"
    assert by_code["HUMSVC127"]["grade"] == "B+"
    assert by_code["HUMSVC103"]["course_title"] == "Group Work Skills"
    assert by_code["HUMSVC103"]["term"] == "FA2018"


def test_parser_handles_madison_college_vertical_course_rows():
    parser = TranscriptHeuristicParser()
    text = """
    Madison College Unofficial
    Name:
    Tiana Richmond-Lee
    ID:
    2893109
    Beginning of Student Record
    Spring 2025
    Subject
    Course #
    Course Title
    Attempted
    Earned
    Grade
    COMM
    20810205
    Small Group & Interpsni Comm
    3.00
    3.00
    A
    12.00
    MATH
    10804134
    Mathematical Reasoning
    3.00
    3.00
    BC
    7.50
    Course Topic:
    ARP: Math Reasoning W Workshop
    MATHABE
    77854782
    Reasoning Workshop
    2.00
    2.00
    BC*
    READING
    10838105
    Intro Reading & Study Skills
    3.00
    3.00
    B
    9.00
    Term Totals
    11.00
    11.00
    39.00
    Term GPA
    3.545
    Cum Totals
    32.00
    17.00
    46.50
    Cum GPA
    2.735
    Summer 2025
    ENGLISH
    10801195
    Written Communication
    3.00
    3.00
    AB
    10.50
    Fall 2025
    FOUNHLTH
    31501153
    Body Structure & Function
    3.00
    3.00
    BC
    7.50
    Spring 2026
    CRIMJUST
    10504170
    Introduction to Corrections
    3.00
    3.00
    NR
    0.00
    Transfer Credits
    Fall 2025
    ENGLISH
    20801229
    Contemporary Literature
    3.00
    3.00
    T
    0.00
    Other Credits
    NURSNA
    30543300
    Nursing Assistant
    3.00
    T
    """.strip()

    parsed = parser.parse(text, "college_transcript")

    assert parsed["student"]["name"] == "Tiana Richmond-Lee"
    assert parsed["student"]["student_id"] == "2893109"
    assert parsed["academic_summary"]["gpa"] == 2.735
    assert parsed["academic_summary"]["total_credits_attempted"] == 32.0
    assert parsed["academic_summary"]["total_credits_earned"] == 17.0
    courses = [course for term in parsed["terms"] for course in term["courses"]]
    assert len(courses) == 9
    by_code = {course["course_code"]: course for course in courses}
    assert by_code["COMM20810205"]["grade"] == "A"
    assert by_code["MATH10804134"]["grade"] == "BC"
    assert by_code["MATHABE77854782"]["grade"] == "BC*"
    assert by_code["ENGLISH10801195"]["grade"] == "AB"
    assert by_code["CRIMJUST10504170"]["grade"] == "NR"
    assert by_code["ENGLISH20801229"]["grade"] == "T"
    assert by_code["NURSNA30543300"]["grade"] == "T"


def test_parser_prefers_madison_college_watermark_over_course_line_for_institution():
    parser = TranscriptHeuristicParser()
    text = """
    Madison College UnofficialMadison College Unofficial
    Name: Tiana Richmond-Lee
    ID: 2893109
    Spring 2019
    ENGLISH 10831103 Intro To College Writing 3.00 0.00 F 0.00
    """.strip()

    parsed = parser.parse(text, "college_transcript")

    assert parsed["institutions"][0]["name"] == "Madison College"


def test_parser_handles_logan_district_flattened_transcript_rows():
    parser = TranscriptHeuristicParser()
    text = """
    Institution
    4900510
    Logan High
    Logan School District
    162 West 100 South
    Logan, UT 84321
    Student
    Emi Tice
    110 LJ Circle,
    Logan, UT 84321
    808-389-6066
    Female
    DOB: 2007-10-16
    Academic Record
    Summary TypeHours Attempted Hours Earned GPA Class Rank Class Size
    All 25.250 25.250 3.803 68 320
    Weighted
    Academic Session
    Institution Academic YearAcademic Level
    Logan High School 2025-2026
    Course no Title Session Grade Credits
    Peer Tutor 1 A 0.250
    Financial Literacy 1 A 0.250
    BIOL 1010 CE 1 A 0.500
    Early Childhood Education 1 1 A 0.250
    STAT 1040 CE 1 A- 0.250
    Homeroom 1 P 0.000
    US Government & Citizen 1 A 0.250
    Spirit Squad 1 A 0.250
    Summary TypeHours Attempted Hours Earned GPA
    All
    Academic Session
    Institution Academic YearAcademic Level
    Kahuku High & Inter2024-2025
    Course no Title Session Grade Credits
    Found Business & Marketing 1 A 0.250
    Geography 1 A 0.250
    Ensemble 1 1 A 0.250
    """.strip()

    parsed = parser.parse(text, "high_school_transcript")

    assert parsed["student"]["name"] == "Emi Tice"
    assert parsed["student"]["date_of_birth"] == "2007-10-16"
    assert parsed["student"]["address"]["city"] == "Logan"
    assert parsed["institutions"][0]["name"] == "Logan High"
    assert parsed["academic_summary"]["gpa"] == 3.803
    assert parsed["academic_summary"]["total_credits_earned"] == 25.25
    assert parsed["academic_summary"]["class_rank"] == "68/320"
    courses = [course for term in parsed["terms"] for course in term["courses"]]
    assert len(courses) == 11
    by_title = {course["course_title"]: course for course in courses}
    assert by_title["BIOL 1010 CE"]["grade"] == "A"
    assert by_title["STAT 1040 CE"]["grade"] == "A-"
    assert by_title["Early Childhood Education 1"]["credits"] == 0.25
    assert by_title["Found Business & Marketing"]["term"] == "2024-2025 Kahuku High & Inter"


def test_parser_handles_session_terms_and_transfer_grades():
    parser = TranscriptHeuristicParser()
    text = """
    --------------- (F1T) Fall I 2007 ---------------
    BSAD101 Accounting Principles I 3.00 TR
    --------------- (F2T) Fall II 2007 --------------
    CS208 Discrete Mathematics 3.00 F
    """.strip()

    parsed = parser.parse(text, "college_transcript")

    assert len(parsed["terms"]) == 2
    assert parsed["terms"][0]["term_name"] == "--------------- (F1T) Fall I 2007 ---------------"
    assert parsed["terms"][0]["courses"][0]["grade"] == "TR"
    assert parsed["terms"][1]["courses"][0]["grade"] == "F"


def test_parser_skips_totals_and_legend_example_rows():
    parser = TranscriptHeuristicParser()
    text = """
    -------------- (S1T) Spring I 2015 --------------
    TOTAL 121.00 78.00 121.00 78.00 204.00 2.615
    EN306B Prof Writing in the Disciplines 3.00 B
    Example: ACC201 (Accounting 201)
    AC20I (Principles of Accounting I)
    """.strip()

    parsed = parser.parse(text, "college_transcript")
    courses = parsed["terms"][0]["courses"]

    assert len(courses) == 1
    assert courses[0]["course_code"] == "EN306B"


def test_parser_handles_umkc_style_terms_courses_and_identity_fields():
    parser = TranscriptHeuristicParser()
    text = """
    Name: Woolsey,Alan Leroy
    ID: 16215673
    Date of Birth: 10/19/XXXX
    Permanent Address as of 05/15/2015:
    29300 E 65th St
    Blue Springs, MO 64014-4223
    FALL 2015 Local Campus Credits Grad Bus-Ad-MBA
    Mgt 5501 Int'l Business Environment A 1.5
    Pub Ad 5506 Management in Context A 1.5
    SPNG 2016 Local Campus Credits Grad Bus-Ad-MBA
    Mgt 5502 Leadership in Organizations B+ 1.5
    Rl Est 5556 Ent Real Estate Process W 3.0
    """.strip()

    parsed = parser.parse(text, "college_transcript")

    assert parsed["student"]["name"] == "Alan Leroy Woolsey"
    assert parsed["student"]["student_id"] == "16215673"
    assert parsed["student"]["date_of_birth"] == "10/19/XXXX"
    assert parsed["student"]["address"]["street"] == "29300 E 65th St"
    assert len(parsed["terms"]) == 2
    assert parsed["terms"][0]["courses"][0]["course_code"] == "Mgt5501"
    assert parsed["terms"][0]["courses"][0]["grade"] == "A"
    assert parsed["terms"][0]["courses"][1]["course_code"] == "PubAd5506"
    second_term_courses = {course["course_code"]: course["grade"] for course in parsed["terms"][1]["courses"]}
    assert second_term_courses["Mgt5502"] == "B+"
    assert second_term_courses["RlEst5556"] == "W"


def test_parser_handles_code_less_high_school_transcript_rows():
    parser = TranscriptHeuristicParser()
    text = """
    Larsen, Hailey Dee Course Name
    24-25 Columbia High School
    Spanish 2 A 11 A 1.00
    Advanced Algebra A 11 A 1.00
    Athletic PE 11 P 1.00
    GPA Summary
    Total Credits Earned: 53.5
    Cum Wt GPA: 4.0816
    Cum UnWt GPA: 3.9592
    Rank: 23 out of 289
    Columbia High School
    Student Number:
    1317047295
    Birth Date:
    10/16/2007
    """.strip()

    parsed = parser.parse(text, "high_school_transcript")

    assert parsed["student"]["name"] == "Hailey Dee Larsen"
    assert parsed["student"]["student_id"] == "1317047295"
    assert parsed["student"]["date_of_birth"] == "10/16/2007"
    assert parsed["institutions"][0]["name"] == "Columbia High School"
    assert parsed["academic_summary"]["total_credits_earned"] == 53.5
    assert len(parsed["terms"]) == 1
    courses = parsed["terms"][0]["courses"]
    assert len(courses) == 3
    assert courses[0]["course_title"] == "Spanish 2 A"
    assert courses[0]["grade"] == "A"
    assert courses[2]["grade"] == "P"


def test_parser_handles_formatted_xml_transcript_rows():
    parser = TranscriptHeuristicParser()
    text = """
    Formatted XML Content
    HighSchoolTranscript
    Source
    Organization
    OrganizationName
    Layton High
    Student
    Person
    AgencyAssignedID
    0002105176
    Birth
    BirthDate
    2008-05-31
    Name
    FirstName
    CHASITY
    LastName
    HALL
    Contacts
    Address
    AddressLine
    1132 E 1300 NORTH ST,
    City
    LAYTON
    StateProvinceCode
    UT
    PostalCode
    84040
    AcademicRecord
    AcademicSummary
    AcademicSummaryType
    All
    GPA
    CreditHoursAttempted
    0.000
    CreditHoursEarned
    0.000
    GradePointAverage
    3.271
    ClassRank
    381
    ClassSize
    721
    AcademicSession
    AcademicSessionDetail
    SessionSchoolYear
    2024-2025
    School
    OrganizationName
    CATALYST CENTER
    Course
    CourseCreditEarned
    1.000
    CourseSupplementalGrade
    SupplementalGradeSubSession
    1
    Grade
    B-
    CourseSupplementalGrade
    SupplementalGradeSubSession
    4
    Grade
    B+
    AgencyCourseID
    07080000115
    CourseTitle
    Honors Sec Math 3
    """.strip()

    parsed = parser.parse(text, "high_school_transcript")

    assert parsed["student"]["name"] == "Chasity Hall"
    assert parsed["student"]["student_id"] == "0002105176"
    assert parsed["student"]["date_of_birth"] == "2008-05-31"
    assert parsed["student"]["address"]["street"] == "1132 E 1300 NORTH ST"
    assert parsed["institutions"][0]["name"] == "Layton High"
    assert parsed["academic_summary"]["gpa"] == 3.271
    assert parsed["academic_summary"]["class_rank"] == "381/721"
    assert parsed["terms"][0]["courses"][0]["course_code"] == "07080000115"
    assert parsed["terms"][0]["courses"][0]["grade"] == "B+"


def test_parser_handles_brandon_valley_two_column_transcript_rows():
    parser = TranscriptHeuristicParser()
    text = """
    Brandon Valley High School
    Name EMALEIGH SMITH
    State ID 0000127630487
    Birthdate 05/18/2007
    Address 512 S 4TH AVE
    BRANDON, SD 57005
    Total Earned Credits. 22 500
    Rank. 230 of 313
    Cumulative GPA Credits 23 000
    Cumulative GPA 2 826
    Grade 9
    Grade 10
    Course
    Year
    To Be
    Earned
    S1
    S2
    Course
    Year
    To Be
    Earned
    S1
    S2
    Earned
    Credits
    Earned
    Credits
    8th Grade Health
    2021
    0 000
    0 000
    P
    02052 ALGEBRA I
    2023
    0.000
    0 500
    B-
    02052 ALGEBRA I
    2022
    0 000
    0.500
    D+
    D-
    01002 ENGLISH 10
    2023
    0.000
    1000
    B
    B
    Grade 11
    Grade 12
    01102/01054 ENG 11
    2024
    0 000
    1 000
    B
    C-
    HC 106 CNA CERTIFICATION (DC)
    2025
    0 000
    0 500
    B
    08002 TEAM SPORTS
    2025
    0 000
    0 500 A
    """.strip()

    parsed = parser.parse(text, "high_school_transcript")

    assert parsed["student"]["name"] == "Emaleigh Smith"
    assert parsed["student"]["student_id"] == "0000127630487"
    assert parsed["student"]["date_of_birth"] == "05/18/2007"
    assert parsed["student"]["address"]["city"] == "Brandon"
    assert parsed["academic_summary"]["gpa"] == 2.826
    assert parsed["academic_summary"]["total_credits_earned"] == 22.5
    assert parsed["academic_summary"]["total_credits_attempted"] == 23.0
    assert parsed["academic_summary"]["class_rank"] == "230/313"

    courses = [course for term in parsed["terms"] for course in term["courses"]]
    by_title = {course["course_title"]: course for course in courses}
    assert by_title["8th Grade Health"]["grade"] == "P"
    assert by_title["8th Grade Health"]["term"] == "Grade 9 2021"
    assert by_title["ALGEBRA I"]["course_code"] == "02052"
    assert by_title["ALGEBRA I"]["credits"] == 0.5
    assert by_title["ENG 11"]["course_code"] == "01102/01054"
    assert by_title["ENG 11"]["grade"] == "C-"
    assert by_title["CNA CERTIFICATION (DC)"]["course_code"] == "HC106"
    assert by_title["CNA CERTIFICATION (DC)"]["term"] == "Grade 12 2025"
    assert by_title["TEAM SPORTS"]["grade"] == "A"


def test_parser_handles_parchment_high_school_transcript_rows():
    parser = TranscriptHeuristicParser()
    text = """
    Official Transcript
    Prepared for: Dakota State University on 01/20/2026
    Parchment Student ID: 63080704
    Student Name: Dominguez, Erik J
    Addison Trail High School
    ID: 3222095 State ID: 602563064 Birth Date: 10/25/2003 Gender: M
    Address:725 W Willow Glen St
    Addison, IL 60101
    SEM 1
    SEM 2
    SS
    21-22 Addison Trail High School
    Computer Science 2: Mobile App Develop
    A 1.00
    Consumer Management
    8 1.00
    English 12
    A.
    1.00
    A
    1.00
    FE 11/12 S1
    A
    :00
    20-21 Addison Trail High School
    Algebra 2
    A
    1.00
    A 1.00
    PE 11/12/82
    33
    3.00
    """.strip()

    parsed = parser.parse(text, "high_school_transcript")

    assert parsed["student"]["name"] == "Erik J Dominguez"
    assert parsed["student"]["student_id"] == "63080704"
    assert parsed["student"]["date_of_birth"] == "10/25/2003"
    assert parsed["student"]["address"]["city"] == "Addison"
    assert parsed["institutions"][0]["name"] == "Addison Trail High School"

    terms = {term["term_name"]: term["courses"] for term in parsed["terms"]}
    assert "21-22 Addison Trail High School" in terms
    assert "20-21 Addison Trail High School" in terms

    by_title = {course["course_title"]: course for courses in terms.values() for course in courses}
    assert by_title["Computer Science 2: Mobile App Develop"]["grade"] == "A"
    assert by_title["Computer Science 2: Mobile App Develop"]["credits"] == 1.0
    assert by_title["Consumer Management"]["grade"] == "B"
    assert by_title["English 12"]["credits"] == 2.0
    assert by_title["FE 11/12 S1"]["credits"] == 1.0
    assert by_title["PE 11/12/82"]["grade"] == "B"


def test_parser_uses_school_report_wrapper_name_when_generic_parse_misses_name():
    parser = TranscriptHeuristicParser()
    text = """
    Booher, Colten
    CEEB: 060417 CAID: 44639945
    FERPA: Waived
    School report
    Personal details
    Name Ms. Denise Noffze, Guidance Counselor
    Name Lutheran High School, 11249 Newlin Gulch Blvd, Parker, CO, USA,
    GPA 3.7143 / 5, Weighted (08/2022 - 05/2025)
    2024-2025 Lutheran High School
    Algebra II /Trigonometry A C 1.00
    """.strip()

    parsed = parser.parse(text, "high_school_transcript")

    assert parsed["student"]["name"] == "Colten Booher"


def test_parser_uses_labeled_student_name_from_later_page_block():
    parser = TranscriptHeuristicParser()
    text = """
    Example High School
    Fall 2025
    ENG101 English Composition 1.00 A
    Student Name
    Example High
    School
    Colten Timothy Booher
    Date of Birth
    01/01/2008
    """.strip()

    parsed = parser.parse(text, "high_school_transcript")

    assert parsed["student"]["name"] == "Colten Timothy Booher"


def test_parser_handles_student_achievement_summary_transcript_rows():
    parser = TranscriptHeuristicParser()
    text = """
    Student Name
    Lutheran High
    School
    Colten Timothy Booher
    Date of Birth Current Grade Gender
    12/11/2007 12 Male
    Student Achievement Summary
    Cumulative
    GPA
    Cumulative
    UGPA
    Weighted
    Rank Out of Graduation Date
    3.71 3.47 112 246CEEB code: 060417
    9th Grade 10th Grade
    2022-2023 Lutheran High School 2023-2024 Lutheran High School Grading ScaleCourse Title S1 S2 Credits Course Title S1 S2 Credits
    Algebra I A C 1.00 Drawing I/Painting I A 0.50 Un-weighted grades:
    Driver's Ed Sem 1 A 0.50 French II A A 1.00 A = 4 B = 3
    Earth Science A 0.50 Geometry B B 1.00 C = 2 D = 1
    Team Strength 2nd Sem A 0.50 Team Strength 1st Sem A 0.50
    Theology I B B 1.00 Team Strength 2nd Sem A 0.50
    World Geography B 0.50 Theology II B B 1.00 Weighted grades:
    World Literature A A 1.00 Honors (H)
    Annual GPA 3.67 7.50 and AP courses
    11th Grade 12th Grade Standard Schedule
    2024-2025 Lutheran High School 2025-2026 Lutheran High School 24 credits plus 0.5 credit of
    Course Title S1 S2 Credits Course Title S1 S2 Credits
    Algebra II /Trigonometry A C 1.00 AP Lit/Comp AP 0.00
    AP Language AP B B 1.00 AP US Government AP 0.00
    AP US History AP B A 1.00 Finance H 0.00
    Drawing II/Painting II A 0.50 Physics: Electricity & Waves H 0.00
    French III A A 1.00 Physics: Mechanics H 0.00
    Honors General Chemistry H C 0.50 Pre-Calculus 0.00
    Honors Inorganic Chemistry H C 0.50 Psychology 0.00
    Personal Finance S A 0.50 Theology IV 0.00
    Sales & Marketing B 0.50
    Team Strength 1st Sem A 0.50 Annual GPA 0.00 0.00
    Team Strength 2nd Sem A 0.50
    Theology III B B 1.00
    Annual GPA 3.65 8.50
    """.strip()

    parsed = parser.parse(text, "high_school_transcript")

    assert parsed["student"]["name"] == "Colten Timothy Booher"
    assert parsed["student"]["date_of_birth"] == "12/11/2007"
    assert parsed["institutions"][0]["name"] == "Lutheran High School"
    assert parsed["academic_summary"]["gpa"] == 3.71
    assert parsed["academic_summary"]["class_rank"] == "112/246"
    courses = [course for term in parsed["terms"] for course in term["courses"]]
    assert len(courses) >= 18
    by_title = {course["course_title"]: course for course in courses}
    assert by_title["Algebra I"]["grade"] == "C"
    assert by_title["Drawing I/Painting"]["credits"] == 0.5
    assert by_title["AP Language"]["grade"] == "B"
    assert by_title["AP Lit/Comp"]["credits"] == 0.0
    assert by_title["Theology III"]["grade"] == "B"
