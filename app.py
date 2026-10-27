import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px

DB = Path(__file__).with_name("medicare.db")
st.set_page_config(page_title="MediCare | Medicine Reminder", page_icon="💊", layout="wide")

def connect():
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS medicines(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, dosage TEXT NOT NULL,
            frequency TEXT NOT NULL, times TEXT NOT NULL, start_date TEXT NOT NULL,
            end_date TEXT, instructions TEXT DEFAULT '', notes TEXT DEFAULT '',
            active INTEGER DEFAULT 1, created_at TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS dose_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, medicine_id INTEGER NOT NULL,
            scheduled_date TEXT NOT NULL, scheduled_time TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('Taken','Skipped')), recorded_at TEXT NOT NULL,
            UNIQUE(medicine_id, scheduled_date, scheduled_time),
            FOREIGN KEY(medicine_id) REFERENCES medicines(id))""")
        con.commit()

def medicines(active_only=False):
    with connect() as con:
        q = "SELECT * FROM medicines" + (" WHERE active=1" if active_only else "") + " ORDER BY active DESC,name"
        return pd.DataFrame([dict(r) for r in con.execute(q).fetchall()])

def logs():
    with connect() as con:
        q = """SELECT l.*,m.name AS medicine_name,m.dosage FROM dose_logs l
               JOIN medicines m ON m.id=l.medicine_id
               ORDER BY scheduled_date DESC,scheduled_time DESC"""
        return pd.DataFrame([dict(r) for r in con.execute(q).fetchall()])

def add_medicine(name,dosage,frequency,times,start,end,instructions,notes):
    with connect() as con:
        con.execute("""INSERT INTO medicines(name,dosage,frequency,times,start_date,end_date,
                    instructions,notes,active,created_at) VALUES(?,?,?,?,?,?,?,?,1,?)""",
                    (name.strip(),dosage.strip(),frequency,",".join(times),start.isoformat(),
                     end.isoformat() if end else None,instructions.strip(),notes.strip(),
                     datetime.now().isoformat(timespec="seconds")))
        con.commit()

def mark_dose(mid,day,tm,status):
    with connect() as con:
        con.execute("""INSERT INTO dose_logs(medicine_id,scheduled_date,scheduled_time,status,recorded_at)
                       VALUES(?,?,?,?,?) ON CONFLICT(medicine_id,scheduled_date,scheduled_time)
                       DO UPDATE SET status=excluded.status,recorded_at=excluded.recorded_at""",
                    (int(mid),day,tm,status,datetime.now().isoformat(timespec="seconds")))
        con.commit()

def scheduled(meds, history, day):
    result=[]
    for _,m in meds.iterrows():
        start=date.fromisoformat(m["start_date"])
        end=date.fromisoformat(m["end_date"]) if m["end_date"] else None
        if not int(m["active"]) or day < start or (end and day > end):
            continue
        for tm in m["times"].split(","):
            found=history[(history.medicine_id==m["id"]) & (history.scheduled_date==day.isoformat()) &
                          (history.scheduled_time==tm)] if not history.empty else pd.DataFrame()
            result.append({"id":int(m["id"]),"name":m["name"],"dosage":m["dosage"],"time":tm,
                           "instructions":m["instructions"] or "—",
                           "status":found.iloc[0]["status"] if not found.empty else "Pending"})
    return sorted(result,key=lambda x:x["time"])

init_db()
all_meds=medicines()
active_meds=medicines(True)
history=logs()
today=date.today()

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html,body,[class*="css"]{font-family:Inter,sans-serif}
.stApp{background:#F4F7FB;color:#172B4D}
[data-testid="stSidebar"]{background:#142D4E}
[data-testid="stSidebar"] *{color:#F8FAFC}
.block-container{padding-top:1.6rem;max-width:1450px}
div[data-testid="stMetric"]{background:white;border:1px solid #E2E8F0;border-radius:15px;padding:15px}
.stButton>button,.stDownloadButton>button{border-radius:10px;font-weight:600}
.stButton>button[kind="primary"]{background:#2878D0;border-color:#2878D0;color:white}
</style>""",unsafe_allow_html=True)

with st.sidebar:
    st.markdown("# 💊 MediCare")
    st.caption("MEDICINE REMINDER SYSTEM")
    page=st.radio("NAVIGATION",["🏠 Dashboard","💊 Medicines","➕ Add Medicine","⏰ Reminders","📊 History & Reports","⚙️ Settings"])
    st.markdown("---")
    st.caption(today.strftime("%A, %d %B %Y"))
    st.caption("Follow your healthcare professional's instructions.")

if page=="🏠 Dashboard":
    st.title("Good day 👋")
    st.caption("Your medication schedule at a glance.")
    schedule=scheduled(active_meds,history,today)
    taken=sum(x["status"]=="Taken" for x in schedule)
    pending=sum(x["status"]=="Pending" for x in schedule)
    c1,c2,c3,c4=st.columns(4)
    c1.metric("💊 Active medicines",len(active_meds))
    c2.metric("📅 Scheduled doses",len(schedule))
    c3.metric("✅ Marked taken",taken)
    c4.metric("⏳ Pending",pending)
    left,right=st.columns([1.5,1])
    with left:
        st.subheader("Today's medication schedule")
        if not schedule: st.info("No doses scheduled today. Add a medicine to get started.")
        for x in schedule:
            with st.container(border=True):
                a,b=st.columns([3,2])
                a.markdown(f"**{x['time']} · {x['name']}**")
                a.caption(f"{x['dosage']} · {x['instructions']}")
                b.write(f"Status: **{x['status']}**")
                if x["status"]=="Pending":
                    q1,q2=b.columns(2)
                    if q1.button("Taken ✓",key=f"dt{x['id']}{x['time']}"):
                        mark_dose(x["id"],today.isoformat(),x["time"],"Taken"); st.rerun()
                    if q2.button("Skip",key=f"ds{x['id']}{x['time']}"):
                        mark_dose(x["id"],today.isoformat(),x["time"],"Skipped"); st.rerun()
    with right:
        st.subheader("Dose status")
        if schedule:
            chart=pd.DataFrame([{"Status":s,"Count":sum(x["status"]==s for x in schedule)} for s in ["Taken","Pending","Skipped"]])
            fig=px.pie(chart,names="Status",values="Count",hole=.6,color="Status",
                       color_discrete_map={"Taken":"#16A34A","Pending":"#F59E0B","Skipped":"#DC2626"})
            fig.update_layout(margin=dict(t=10,b=10,l=10,r=10),paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig,use_container_width=True)
        st.info("This version displays schedules inside the app. Notifications when the app is closed require a separate notification service.")

elif page=="💊 Medicines":
    st.title("💊 Medicines")
    if all_meds.empty: st.info("No medicines added yet.")
    else:
        search=st.text_input("Search by name or dosage")
        filt=st.selectbox("Show medicines",["All","Active","Archived"])
        view=all_meds.copy()
        if search.strip():
            q=search.strip().lower()
            view=view[view.name.str.lower().str.contains(q,na=False)|view.dosage.str.lower().str.contains(q,na=False)]
        if filt=="Active": view=view[view.active==1]
        if filt=="Archived": view=view[view.active==0]
        for _,m in view.iterrows():
            with st.container(border=True):
                a,b,c=st.columns([3,2,1])
                a.markdown(f"### 💊 {m['name']}")
                a.write(f"**Dosage:** {m['dosage']} · **Frequency:** {m['frequency']}")
                a.caption(f"Times: {m['times']} · {m['start_date']} to {m['end_date'] or 'No end date'}")
                b.write(f"**Instructions:** {m['instructions'] or '—'}")
                b.caption(m["notes"] or "No notes")
                if int(m["active"]):
                    if c.button("Archive",key=f"arc{m['id']}"):
                        with connect() as con: con.execute("UPDATE medicines SET active=0 WHERE id=?",(int(m["id"]),)); con.commit()
                        st.rerun()
                else:
                    if c.button("Reactivate",key=f"react{m['id']}"):
                        with connect() as con: con.execute("UPDATE medicines SET active=1 WHERE id=?",(int(m["id"]),)); con.commit()
                        st.rerun()

elif page=="➕ Add Medicine":
    st.title("➕ Add Medicine")
    st.caption("Enter the schedule provided by your healthcare professional.")
    with st.form("add_form",border=True,clear_on_submit=True):
        a,b=st.columns(2)
        name=a.text_input("Medicine name *")
        dosage=b.text_input("Dosage *",placeholder="e.g. as prescribed")
        frequency=a.selectbox("Frequency",["Once daily","Twice daily","Three times daily","Four times daily","Custom"])
        times=b.multiselect("Scheduled time(s) *",["06:00","07:00","08:00","09:00","12:00","13:00","14:00","17:00","18:00","20:00","21:00","22:00"],default=["08:00"])
        extra=st.text_input("Other times (optional, comma-separated HH:MM)",placeholder="e.g. 08:30, 15:30")
        a,b=st.columns(2)
        start=a.date_input("Start date",today)
        has_end=b.checkbox("Set end date")
        end=b.date_input("End date",today+timedelta(days=7),disabled=not has_end)
        instructions=st.text_input("Instructions (optional)")
        notes=st.text_area("Notes (optional)",height=75)
        submit=st.form_submit_button("Save medicine",type="primary",use_container_width=True)
        if submit:
            chosen=list(times)
            if extra.strip(): chosen += [x.strip() for x in extra.split(",") if x.strip()]
            valid=[]
            try:
                for tm in chosen:
                    datetime.strptime(tm,"%H:%M")
                    if tm not in valid: valid.append(tm)
            except ValueError:
                st.error("Use valid 24-hour times, e.g. 08:30.")
                valid=[]
            if not name.strip() or not dosage.strip(): st.error("Medicine name and dosage are required.")
            elif not valid: st.error("Select or enter at least one valid time.")
            elif has_end and end<start: st.error("End date cannot be before start date.")
            else:
                add_medicine(name,dosage,frequency,sorted(valid),start,end if has_end else None,instructions,notes)
                st.success("Medicine saved."); st.rerun()

elif page=="⏰ Reminders":
    st.title("⏰ Reminders")
    st.caption("Review scheduled doses and record what happened.")
    day=st.date_input("Choose date",today,key="reminder_date")
    schedule=scheduled(active_meds,logs(),day)
    if not schedule: st.info("No doses scheduled for this date.")
    for x in schedule:
        with st.container(border=True):
            a,b,c=st.columns([3,2,2])
            a.markdown(f"**{x['time']} · {x['name']}**")
            a.caption(f"{x['dosage']} · {x['instructions']}")
            b.write(f"Status: **{x['status']}**")
            if x["status"]=="Pending":
                if c.button("Mark taken",key=f"rt{x['id']}{day}{x['time']}",type="primary"):
                    mark_dose(x["id"],day.isoformat(),x["time"],"Taken"); st.rerun()
                if c.button("Mark skipped",key=f"rs{x['id']}{day}{x['time']}"):
                    mark_dose(x["id"],day.isoformat(),x["time"],"Skipped"); st.rerun()
            elif c.button("Reset status",key=f"rr{x['id']}{day}{x['time']}"):
                with connect() as con:
                    con.execute("DELETE FROM dose_logs WHERE medicine_id=? AND scheduled_date=? AND scheduled_time=?",(x["id"],day.isoformat(),x["time"])); con.commit()
                st.rerun()

elif page=="📊 History & Reports":
    st.title("📊 History & Reports")
    data=logs()
    if data.empty: st.info("Dose history appears after you mark doses as taken or skipped.")
    else:
        a,b=st.columns(2)
        start=a.date_input("From date",today-timedelta(days=30))
        end=b.date_input("To date",today)
        data["scheduled_date"]=pd.to_datetime(data["scheduled_date"],errors="coerce")
        view=data[(data.scheduled_date.dt.date>=start)&(data.scheduled_date.dt.date<=end)].copy()
        st.dataframe(view[["scheduled_date","scheduled_time","medicine_name","dosage","status","recorded_at"]].rename(columns={
            "scheduled_date":"Date","scheduled_time":"Scheduled time","medicine_name":"Medicine","dosage":"Dosage","status":"Status","recorded_at":"Recorded at"}),
            use_container_width=True,hide_index=True)
        c1,c2,c3=st.columns(3)
        c1.metric("Recorded doses",len(view)); c2.metric("Taken",int((view.status=="Taken").sum())); c3.metric("Skipped",int((view.status=="Skipped").sum()))
        st.download_button("⬇️ Export history (CSV)",view.to_csv(index=False).encode("utf-8"),"medicare_dose_history.csv","text/csv")
        summary=view.groupby("status",as_index=False).size().rename(columns={"size":"Count"})
        fig=px.bar(summary,x="status",y="Count",color="status",color_discrete_map={"Taken":"#16A34A","Skipped":"#DC2626"})
        fig.update_layout(showlegend=False,paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig,use_container_width=True)

elif page=="⚙️ Settings":
    st.title("⚙️ Settings")
    st.subheader("About MediCare")
    st.write("A local medicine schedule and dose-tracking mini-project built with Python, Streamlit, and SQLite.")
    st.write(f"Database file: `{DB.name}`")
    st.info("Data is stored locally. Back up medicare.db to preserve your records.")
    st.warning("This app is for reminders and record-keeping only. It does not prescribe medicines or recommend dosage changes. Follow professional instructions and seek qualified advice if a dose is missed.")

st.markdown("<div style='text-align:center;color:#718096;font-size:12px;padding:25px'>MediCare · Medicine Reminder System · Python + Streamlit + SQLite</div>",unsafe_allow_html=True)
