from app.services.identity_matcher import IdentityMatcher


def test_identity_matcher_matches_cross_school_same_student():
    matcher = IdentityMatcher()
    park = {
        "demographic": {
            "firstName": "Alan",
            "middleName": "L.",
            "lastName": "Woolsey",
            "dateOfBirth": "10/19/70",
            "studentAddress": "29300 E 65th St",
            "studentCity": "Blue Springs",
            "studentState": "MO",
            "studentPostalCode": "64014-4223",
            "institutionName": "Park University",
            "degreeAwardedDate": "05/10/15",
        },
        "metadata": {
            "raw_text_excerpt": "Student Name: Alan L. Woolsey Birth Date: 10/19/70 Park University Bachelor of Science 05/10/15"
        },
    }
    umkc = {
        "demographic": {
            "firstName": "Woolsey,Alan",
            "middleName": "Leroy",
            "lastName": "",
            "dateOfBirth": "10/19/XXXX",
            "studentAddress": "29300 E 65th St",
            "studentCity": "Blue Springs",
            "studentState": "MO",
            "studentPostalCode": "64014-4223",
            "institutionName": "University of Missouri - Kansas City",
        },
        "metadata": {
            "raw_text_excerpt": "Name: Woolsey,Alan Leroy Date of Birth: 10/19/XXXX Degrees Awarded: Park University Computer Information Systems B 05-2015"
        },
    }

    result = matcher.compare_documents(park, umkc)

    assert result["decision"] == "match"
    assert result["same_student_confidence"] >= 0.85
    assert any("address matches strongly" == reason for reason in result["reasons"])
    assert any("date of birth matches on month and day" == reason for reason in result["reasons"])


def test_identity_matcher_rejects_different_students():
    matcher = IdentityMatcher()
    left = {
        "demographic": {
            "firstName": "Jane",
            "middleName": "",
            "lastName": "Smith",
            "dateOfBirth": "01/02/1999",
            "studentAddress": "1 Main St",
            "studentCity": "Denver",
            "studentState": "CO",
            "studentPostalCode": "80014",
            "institutionName": "Example State University",
        },
        "metadata": {"raw_text_excerpt": "Student Name: Jane Smith"},
    }
    right = {
        "demographic": {
            "firstName": "Robert",
            "middleName": "",
            "lastName": "Jones",
            "dateOfBirth": "03/04/1988",
            "studentAddress": "99 Oak Ave",
            "studentCity": "Austin",
            "studentState": "TX",
            "studentPostalCode": "73301",
            "institutionName": "Another College",
        },
        "metadata": {"raw_text_excerpt": "Student Name: Robert Jones"},
    }

    result = matcher.compare_documents(left, right)

    assert result["decision"] == "different"
    assert result["same_student_confidence"] < 0.45
