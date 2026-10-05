import csv
import json

test_records = [
    # Abhishek Sharma - The core example mentioned in the audio
    {
        "student_id": "STU101",
        "student_name": "Abhishek Sharma",
        "roll_no": 1,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Science",
        "chapter": "Gravitation",
        "subtopic": "Universal Law of Gravitation & Numerical Problems",
        "total_questions": 10,
        "attempted": 10,
        "correct": 2,
        "time_taken_mins": 18,
        "test_date": "2026-09-28",
        "difficulty": "Medium",
        "previous_score_pct": 25
    },
    {
        "student_id": "STU101",
        "student_name": "Abhishek Sharma",
        "roll_no": 1,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Science",
        "chapter": "Cell - The Fundamental Unit of Life",
        "subtopic": "Organelles & Cell Membrane",
        "total_questions": 10,
        "attempted": 10,
        "correct": 7,
        "time_taken_mins": 12,
        "test_date": "2026-09-22",
        "difficulty": "Easy",
        "previous_score_pct": 60
    },
    {
        "student_id": "STU101",
        "student_name": "Abhishek Sharma",
        "roll_no": 1,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Mathematics",
        "chapter": "Linear Equations in Two Variables",
        "subtopic": "Graphing & Solutions",
        "total_questions": 10,
        "attempted": 10,
        "correct": 8,
        "time_taken_mins": 22,
        "test_date": "2026-09-29",
        "difficulty": "Medium",
        "previous_score_pct": 70
    },
    {
        "student_id": "STU101",
        "student_name": "Abhishek Sharma",
        "roll_no": 1,
        "class_name": "Class 9",
        "section": "A",
        "subject": "English",
        "chapter": "Grammar",
        "subtopic": "Tenses and Active-Passive Voice",
        "total_questions": 10,
        "attempted": 10,
        "correct": 7,
        "time_taken_mins": 14,
        "test_date": "2026-09-25",
        "difficulty": "Easy",
        "previous_score_pct": 70
    },

    # Priya Verma
    {
        "student_id": "STU102",
        "student_name": "Priya Verma",
        "roll_no": 2,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Science",
        "chapter": "Gravitation",
        "subtopic": "Weightlessness & Free Fall",
        "total_questions": 10,
        "attempted": 10,
        "correct": 3,
        "time_taken_mins": 19,
        "test_date": "2026-09-28",
        "difficulty": "Medium",
        "previous_score_pct": 30
    },
    {
        "student_id": "STU102",
        "student_name": "Priya Verma",
        "roll_no": 2,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Mathematics",
        "chapter": "Linear Equations in Two Variables",
        "subtopic": "Graphing & Solutions",
        "total_questions": 10,
        "attempted": 10,
        "correct": 9,
        "time_taken_mins": 17,
        "test_date": "2026-09-29",
        "difficulty": "Medium",
        "previous_score_pct": 85
    },

    # Rohan Gupta
    {
        "student_id": "STU103",
        "student_name": "Rohan Gupta",
        "roll_no": 3,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Science",
        "chapter": "Gravitation",
        "subtopic": "Universal Law of Gravitation & Numerical Problems",
        "total_questions": 10,
        "attempted": 9,
        "correct": 3,
        "time_taken_mins": 25,
        "test_date": "2026-09-28",
        "difficulty": "Medium",
        "previous_score_pct": 40
    },
    {
        "student_id": "STU103",
        "student_name": "Rohan Gupta",
        "roll_no": 3,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Mathematics",
        "chapter": "Linear Equations in Two Variables",
        "subtopic": "Graphing & Solutions",
        "total_questions": 10,
        "attempted": 8,
        "correct": 5,
        "time_taken_mins": 20,
        "test_date": "2026-09-29",
        "difficulty": "Medium",
        "previous_score_pct": 50
    },

    # Sneha Patel (High Performer)
    {
        "student_id": "STU104",
        "student_name": "Sneha Patel",
        "roll_no": 4,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Science",
        "chapter": "Gravitation",
        "subtopic": "Universal Law & Free Fall",
        "total_questions": 10,
        "attempted": 10,
        "correct": 9,
        "time_taken_mins": 14,
        "test_date": "2026-09-28",
        "difficulty": "Medium",
        "previous_score_pct": 88
    },
    {
        "student_id": "STU104",
        "student_name": "Sneha Patel",
        "roll_no": 4,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Mathematics",
        "chapter": "Linear Equations in Two Variables",
        "subtopic": "Graphing & Solutions",
        "total_questions": 10,
        "attempted": 10,
        "correct": 10,
        "time_taken_mins": 15,
        "test_date": "2026-09-29",
        "difficulty": "Medium",
        "previous_score_pct": 95
    },

    # Aryan Singh (Needs overall academic intervention)
    {
        "student_id": "STU105",
        "student_name": "Aryan Singh",
        "roll_no": 5,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Science",
        "chapter": "Gravitation",
        "subtopic": "Universal Law of Gravitation & Numerical Problems",
        "total_questions": 10,
        "attempted": 8,
        "correct": 2,
        "time_taken_mins": 21,
        "test_date": "2026-09-28",
        "difficulty": "Medium",
        "previous_score_pct": 20
    },
    {
        "student_id": "STU105",
        "student_name": "Aryan Singh",
        "roll_no": 5,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Mathematics",
        "chapter": "Linear Equations in Two Variables",
        "subtopic": "Graphing & Solutions",
        "total_questions": 10,
        "attempted": 9,
        "correct": 4,
        "time_taken_mins": 25,
        "test_date": "2026-09-29",
        "difficulty": "Medium",
        "previous_score_pct": 35
    },

    # Ananya Joshi
    {
        "student_id": "STU106",
        "student_name": "Ananya Joshi",
        "roll_no": 6,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Science",
        "chapter": "Gravitation",
        "subtopic": "Mass and Weight",
        "total_questions": 10,
        "attempted": 10,
        "correct": 8,
        "time_taken_mins": 16,
        "test_date": "2026-09-28",
        "difficulty": "Medium",
        "previous_score_pct": 75
    },

    # Vikram Rao
    {
        "student_id": "STU107",
        "student_name": "Vikram Rao",
        "roll_no": 7,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Science",
        "chapter": "Gravitation",
        "subtopic": "Numerical Problems",
        "total_questions": 10,
        "attempted": 10,
        "correct": 5,
        "time_taken_mins": 20,
        "test_date": "2026-09-28",
        "difficulty": "Medium",
        "previous_score_pct": 50
    },

    # Kavita Nair
    {
        "student_id": "STU108",
        "student_name": "Kavita Nair",
        "roll_no": 8,
        "class_name": "Class 9",
        "section": "A",
        "subject": "Science",
        "chapter": "Gravitation",
        "subtopic": "Universal Law & Gravitational Constant",
        "total_questions": 10,
        "attempted": 9,
        "correct": 3,
        "time_taken_mins": 22,
        "test_date": "2026-09-28",
        "difficulty": "Medium",
        "previous_score_pct": 30
    }
]

# Write CSV
csv_file = "data/students_test_data.csv"
fieldnames = list(test_records[0].keys())
with open(csv_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(test_records)

# Write JSON
json_file = "data/students_test_data.json"
with open(json_file, "w", encoding="utf-8") as f:
    json.dump(test_records, f, indent=2)

print(f"Generated {len(test_records)} test records in {csv_file} and {json_file}")
