# MediCare — Medicine Reminder System

A Python mini-project using Streamlit, SQLite, Pandas, and Plotly.

## Features
- Dashboard with today's scheduled doses and status summary
- Add, search, archive, and reactivate medicine records
- Schedule multiple reminder times and date ranges
- Mark a dose as Taken or Skipped, or reset its status
- Daily schedule and dose history
- CSV export and history chart
- Local SQLite storage
- Medical blue and teal theme with a navy sidebar

## Run
1. Install Python 3.10 or later.
2. Open a terminal in this folder.
3. Run `python -m pip install -r requirements.txt`
4. Run `python -m streamlit run app.py`
5. Open the local URL shown in the terminal (usually http://localhost:8501).

The `medicare.db` database is created automatically.

## Notes
The app displays reminders inside the running application. Notifications while the app is closed require a separate operating-system or hosted notification service. This app is not medical advice and does not prescribe medicines or recommend dose changes. Follow instructions from a qualified healthcare professional.
