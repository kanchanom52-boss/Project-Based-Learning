"""
StudyMateAI - a multi-user study companion built with Streamlit.

Pages: Home, My Profile, AI Assistant Chat, Subjects & Grades, Concept Quiz,
Assignments, Attendance Tracker, Tasks Todo List, Study Planner.

Run:  streamlit run app.py
AI features need an ANTHROPIC_API_KEY (environment variable or .streamlit/secrets.toml).
"""
import calendar
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

DB_PATH = os.environ.get("STUDYMATE_DB", "studymate.db")
MODEL = os.environ.get("STUDYMATE_MODEL", "claude-sonnet-5-5")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

st.set_page_config(page_title="StudyMateAI", page_icon="📚", layout="wide")


# ───────────────────────────── Database ─────────────────────────────
def run(sql, params=()):
    with closing(sqlite3.connect(DB_PATH)) as c:
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid


def q(sql, params=()):
    with closing(sqlite3.connect(DB_PATH)) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, params).fetchall()]


@st.cache_resource
def init_db():
    with closing(sqlite3.connect(DB_PATH)) as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                email TEXT PRIMARY KEY, name TEXT, salt TEXT, pw_hash TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS profiles(
                email TEXT PRIMARY KEY, full_name TEXT, course TEXT, college TEXT,
                year TEXT, goal TEXT, bio TEXT);
            CREATE TABLE IF NOT EXISTS chat(
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, role TEXT,
                content TEXT, ts TEXT);
            CREATE TABLE IF NOT EXISTS subjects(
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, name TEXT,
                credits REAL DEFAULT 3, teacher TEXT);
            CREATE TABLE IF NOT EXISTS grades(
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, subject_id INTEGER,
                exam TEXT, score REAL, max_score REAL, exam_date TEXT);
            CREATE TABLE IF NOT EXISTS quiz_results(
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, topic TEXT,
                score INTEGER, total INTEGER, taken TEXT);
            CREATE TABLE IF NOT EXISTS assignments(
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, title TEXT, subject TEXT,
                due TEXT, priority TEXT, status TEXT DEFAULT 'Pending', notes TEXT);
            CREATE TABLE IF NOT EXISTS attendance(
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, subject_id INTEGER,
                day TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS tasks(
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, task TEXT,
                priority TEXT, done INTEGER DEFAULT 0, created TEXT);
            CREATE TABLE IF NOT EXISTS planner(
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, day TEXT, start TEXT,
                end TEXT, subject TEXT, topic TEXT, done INTEGER DEFAULT 0);
            """
        )
        c.commit()
    return True


# ───────────────────────────── Auth ─────────────────────────────
def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def register(name, email, password):
    email = email.strip().lower()
    if not name.strip():
        return "Please enter your name."
    if not EMAIL_RE.match(email):
        return "Please enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if q("SELECT 1 FROM users WHERE email=?", (email,)):
        return "An account with this email already exists. Please log in."
    salt = secrets.token_hex(16)
    run("INSERT INTO users VALUES(?,?,?,?,?)",
        (email, name.strip(), salt, hash_pw(password, salt), datetime.now().isoformat()))
    run("INSERT INTO profiles(email, full_name) VALUES(?,?)", (email, name.strip()))
    return None


def login(email, password):
    email = email.strip().lower()
    rows = q("SELECT * FROM users WHERE email=?", (email,))
    if not rows:
        return False
    return hmac.compare_digest(rows[0]["pw_hash"], hash_pw(password, rows[0]["salt"]))


def auth_screen():
    st.markdown("# 📚 StudyMateAI")
    st.caption("Your all-in-one AI study companion. Every account keeps its own private data.")
    tab_in, tab_up = st.tabs(["Log in", "Create account"])
    with tab_in:
        with st.form("login_form"):
            email = st.text_input("Email (Gmail)")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", type="primary"):
                if login(email, pw):
                    st.session_state.user = email.strip().lower()
                    st.rerun()
                else:
                    st.error("Incorrect email or password.")
    with tab_up:
        with st.form("signup_form"):
            name = st.text_input("Full name")
            email = st.text_input("Email (Gmail)", key="su_email")
            pw = st.text_input("Password (min 8 characters)", type="password", key="su_pw")
            if st.form_submit_button("Create account", type="primary"):
                err = register(name, email, pw)
                if err:
                    st.error(err)
                else:
                    st.session_state.user = email.strip().lower()
                    st.rerun()


# ───────────────────────────── AI helpers ─────────────────────────────
def get_api_key():
    key = st.session_state.get("user_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        return None


def ai_call(messages, system, max_tokens=1500):
    key = get_api_key()
    if not key:
        return None, "No API key found. Paste your key in the AI settings box on the AI Assistant Chat page."
    try:
        import anthropic
    except ImportError:
        return None, "The 'anthropic' package is missing. Run: python -m pip install anthropic"
    try:
        client = anthropic.Anthropic(api_key=key, timeout=60.0, max_retries=1)
        resp = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system, messages=messages)
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text"), None
    except anthropic.AuthenticationError:
        return None, "Your API key was rejected. Check that you copied the whole key (starts with sk-ant-)."
    except anthropic.NotFoundError:
        return None, f"The model '{MODEL}' was not found for your account. Set STUDYMATE_MODEL to a model you can use."
    except anthropic.RateLimitError:
        return None, "Rate limit reached. Wait a minute and try again."
    except (anthropic.APIConnectionError, anthropic.APITimeoutError):
        return None, ("Could not reach Anthropic within 60 seconds. Check your internet, turn off any VPN or proxy, "
                      "and make sure your firewall or antivirus allows Python to connect to api.anthropic.com.")
    except Exception as e:  # credits, bad request, etc.
        return None, f"AI request failed: {e}"


def profile_context(email):
    p = (q("SELECT * FROM profiles WHERE email=?", (email,)) or [{}])[0]
    bits = [f"{k}: {p.get(k)}" for k in ("full_name", "course", "college", "year", "goal") if p.get(k)]
    return "; ".join(bits)


# ───────────────────────────── Helpers ─────────────────────────────
def grade_point(pct):
    for cut, gp in ((90, 10), (80, 9), (70, 8), (60, 7), (50, 6), (40, 5)):
        if pct >= cut:
            return gp
    return 0


def subjects_of(email):
    return q("SELECT * FROM subjects WHERE email=? ORDER BY name", (email,))


def attendance_summary(email):
    rows = []
    for s in subjects_of(email):
        recs = q("SELECT status, COUNT(*) n FROM attendance WHERE email=? AND subject_id=? GROUP BY status",
                 (email, s["id"]))
        c = {r["status"]: r["n"] for r in recs}
        p, a = c.get("Present", 0), c.get("Absent", 0)
        rows.append({"id": s["id"], "Subject": s["name"], "Attended": p, "Missed": a,
                     "Total": p + a, "Percent": round(100 * p / (p + a), 1) if p + a else 0.0})
    return rows


PRIORITIES = ["High", "Medium", "Low"]


# ───────────────────────────── Pages ─────────────────────────────
def page_home(email):
    name = (q("SELECT name FROM users WHERE email=?", (email,)) or [{"name": ""}])[0]["name"]
    st.title(f"👋 Welcome back, {name.split(' ')[0] if name else 'Student'}!")
    today = date.today().isoformat()

    pending = q("SELECT * FROM assignments WHERE email=? AND status!='Done' ORDER BY due", (email,))
    open_tasks = q("SELECT * FROM tasks WHERE email=? AND done=0", (email,))
    att = attendance_summary(email)
    tot_p = sum(r["Attended"] for r in att)
    tot_t = sum(r["Total"] for r in att)
    grades = q("SELECT score, max_score FROM grades WHERE email=?", (email,))
    avg = round(sum(100 * g["score"] / g["max_score"] for g in grades if g["max_score"]) / len(grades), 1) if grades else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pending assignments", len(pending))
    c2.metric("Open tasks", len(open_tasks))
    c3.metric("Overall attendance", f"{round(100 * tot_p / tot_t, 1)}%" if tot_t else "–")
    c4.metric("Average score", f"{avg}%" if avg is not None else "–")

    left, right = st.columns(2)
    with left:
        st.subheader("⏰ Upcoming deadlines")
        if not pending:
            st.success("Nothing pending. Nice!")
        for a in pending[:5]:
            overdue = a["due"] < today
            st.write(f"{'🔴' if overdue else '🟡'} **{a['title']}** ({a['subject'] or 'General'}) — due {a['due']}"
                     + (" **overdue**" if overdue else ""))
    with right:
        st.subheader("📅 Today's study plan")
        plan = q("SELECT * FROM planner WHERE email=? AND day=? ORDER BY start", (email, today))
        if not plan:
            st.info("No sessions planned today. Add some in Study Planner.")
        for p in plan:
            st.write(f"{'✅' if p['done'] else '⬜'} {p['start']}–{p['end']} · **{p['subject']}** — {p['topic']}")

    low = [r for r in att if r["Total"] and r["Percent"] < 75]
    if low:
        st.warning("Attendance below 75% in: " + ", ".join(r["Subject"] for r in low))


def page_profile(email):
    st.title("👤 My Profile")
    p = (q("SELECT * FROM profiles WHERE email=?", (email,)) or [{}])[0]
    with st.form("profile"):
        st.text_input("Email", value=email, disabled=True)
        full_name = st.text_input("Full name", value=p.get("full_name") or "")
        c1, c2 = st.columns(2)
        course = c1.text_input("Course / Degree", value=p.get("course") or "")
        college = c2.text_input("College / School", value=p.get("college") or "")
        year = c1.text_input("Year / Semester", value=p.get("year") or "")
        goal = c2.text_input("Main goal (e.g. CGPA 9+, crack GATE)", value=p.get("goal") or "")
        bio = st.text_area("About me", value=p.get("bio") or "")
        if st.form_submit_button("Save profile", type="primary"):
            run("UPDATE profiles SET full_name=?, course=?, college=?, year=?, goal=?, bio=? WHERE email=?",
                (full_name, course, college, year, goal, bio, email))
            run("UPDATE users SET name=? WHERE email=?", (full_name, email))
            st.success("Profile saved.")

    with st.expander("🔑 Change password"):
        with st.form("pwform"):
            old = st.text_input("Current password", type="password")
            new = st.text_input("New password (min 8 characters)", type="password")
            if st.form_submit_button("Update password"):
                if not login(email, old):
                    st.error("Current password is wrong.")
                elif len(new) < 8:
                    st.error("New password must be at least 8 characters.")
                else:
                    salt = secrets.token_hex(16)
                    run("UPDATE users SET salt=?, pw_hash=? WHERE email=?", (salt, hash_pw(new, salt), email))
                    st.success("Password updated.")

    with st.expander("⚠️ Delete my account and all data"):
        confirm = st.text_input("Type DELETE to confirm")
        if st.button("Delete account permanently") and confirm == "DELETE":
            for t in ("chat", "grades", "subjects", "quiz_results", "assignments",
                      "attendance", "tasks", "planner", "profiles", "users"):
                run(f"DELETE FROM {t} WHERE email=?", (email,))
            st.session_state.clear()
            st.rerun()


def page_chat(email):
    st.title("🤖 AI Assistant Chat")
    st.caption("Ask doubts, get explanations, summaries, or study tips. Your chats are saved to your account.")
    if not get_api_key():
        st.warning("No AI key found yet. Paste your Anthropic API key below to turn the chat on.")
    with st.expander("🔑 AI settings", expanded=not get_api_key()):
        k = st.text_input("Anthropic API key", type="password",
                          help="Kept only for this browser session. It is not saved in the database.")
        if k.strip():
            k = k.strip().strip("\"'").strip()
            st.session_state["user_api_key"] = k
            ok_shape = k.startswith("sk-ant-") and len(k) > 60
            st.caption(f"Key received: starts with '{k[:7]}', {len(k)} characters. "
                       + ("Looks like a valid key format." if ok_shape else
                          "This does NOT look like a full Anthropic key (should start with sk-ant- and be 100+ characters)."))
    history = q("SELECT role, content FROM chat WHERE email=? ORDER BY id", (email,))
    for m in history:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if history and st.button("🗑️ Clear chat"):
        run("DELETE FROM chat WHERE email=?", (email,))
        st.rerun()

    prompt = st.chat_input("Ask StudyMateAI anything…")
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        msgs = [{"role": m["role"], "content": m["content"]} for m in history[-20:]]
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        msgs.append({"role": "user", "content": prompt})
        system = ("You are StudyMateAI, a friendly, accurate tutor for students. Explain step by step, "
                  "use simple examples, and keep answers focused. Student profile: "
                  + (profile_context(email) or "not provided") + ".")
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                reply, err = ai_call(msgs, system)
            if err:
                st.error(err)
            else:
                st.markdown(reply)
                run("INSERT INTO chat(email, role, content, ts) VALUES(?,?,?,?)",
                    (email, "user", prompt, datetime.now().isoformat()))
                run("INSERT INTO chat(email, role, content, ts) VALUES(?,?,?,?)",
                    (email, "assistant", reply, datetime.now().isoformat()))


def page_grades(email):
    st.title("📊 Subjects & Grades")
    subs = subjects_of(email)
    t1, t2, t3 = st.tabs(["Subjects", "Add marks", "Report"])

    with t1:
        with st.form("add_subject", clear_on_submit=True):
            c1, c2, c3 = st.columns([3, 1, 2])
            name = c1.text_input("Subject name")
            credits = c2.number_input("Credits", 0.5, 10.0, 3.0, 0.5)
            teacher = c3.text_input("Teacher (optional)")
            if st.form_submit_button("Add subject", type="primary") and name.strip():
                run("INSERT INTO subjects(email, name, credits, teacher) VALUES(?,?,?,?)",
                    (email, name.strip(), credits, teacher))
                st.rerun()
        for s in subs:
            c1, c2 = st.columns([6, 1])
            c1.write(f"**{s['name']}** · {s['credits']} credits" + (f" · {s['teacher']}" if s["teacher"] else ""))
            if c2.button("Delete", key=f"ds{s['id']}"):
                for t in ("grades", "attendance"):
                    run(f"DELETE FROM {t} WHERE subject_id=? AND email=?", (s["id"], email))
                run("DELETE FROM subjects WHERE id=? AND email=?", (s["id"], email))
                st.rerun()

    with t2:
        if not subs:
            st.info("Add a subject first.")
        else:
            with st.form("add_grade", clear_on_submit=True):
                sid = st.selectbox("Subject", [s["id"] for s in subs],
                                   format_func=lambda i: next(s["name"] for s in subs if s["id"] == i))
                exam = st.text_input("Exam / Test name (e.g. Mid-term)")
                c1, c2, c3 = st.columns(3)
                score = c1.number_input("Marks obtained", 0.0, 10000.0, 0.0, 0.5)
                mx = c2.number_input("Maximum marks", 1.0, 10000.0, 100.0, 1.0)
                d = c3.date_input("Date", date.today())
                if st.form_submit_button("Save marks", type="primary"):
                    if score > mx:
                        st.error("Marks obtained cannot exceed maximum marks.")
                    else:
                        run("INSERT INTO grades(email, subject_id, exam, score, max_score, exam_date) VALUES(?,?,?,?,?,?)",
                            (email, sid, exam or "Exam", score, mx, d.isoformat()))
                        st.success("Saved.")

    with t3:
        rows = []
        for s in subs:
            gs = q("SELECT * FROM grades WHERE email=? AND subject_id=?", (email, s["id"]))
            if gs:
                pct = sum(100 * g["score"] / g["max_score"] for g in gs) / len(gs)
                rows.append({"Subject": s["name"], "Credits": s["credits"], "Exams": len(gs),
                             "Average %": round(pct, 1), "Grade point": grade_point(pct)})
        if not rows:
            st.info("No marks recorded yet.")
        else:
            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True, use_container_width=True)
            st.bar_chart(df.set_index("Subject")["Average %"])
            cr = df["Credits"].sum()
            cgpa = (df["Grade point"] * df["Credits"]).sum() / cr if cr else 0
            c1, c2 = st.columns(2)
            c1.metric("Overall average", f"{df['Average %'].mean():.1f}%")
            c2.metric("Estimated CGPA (10-point)", f"{cgpa:.2f}")
            with st.expander("All exam records"):
                recs = q("""SELECT g.id, s.name subject, g.exam, g.score, g.max_score, g.exam_date
                            FROM grades g JOIN subjects s ON s.id=g.subject_id
                            WHERE g.email=? ORDER BY g.exam_date DESC""", (email,))
                for r in recs:
                    c1, c2 = st.columns([6, 1])
                    c1.write(f"{r['exam_date']} · **{r['subject']}** · {r['exam']}: {r['score']}/{r['max_score']}")
                    if c2.button("Delete", key=f"dg{r['id']}"):
                        run("DELETE FROM grades WHERE id=? AND email=?", (r["id"], email))
                        st.rerun()


def parse_quiz(text):
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("["), text.rfind("]")
    data = json.loads(text[start:end + 1])
    out = []
    for it in data:
        opts = it["options"]
        ai = int(it["answer_index"])
        if len(opts) >= 2 and 0 <= ai < len(opts):
            out.append({"question": it["question"], "options": opts, "answer_index": ai,
                        "explanation": it.get("explanation", "")})
    if not out:
        raise ValueError("no valid questions")
    return out


def page_quiz(email):
    st.title("🧠 Concept Quiz")
    ss = st.session_state

    if "quiz" not in ss:
        with st.form("quiz_setup"):
            topic = st.text_input("Topic (e.g. Newton's laws, Binary trees, Photosynthesis)")
            c1, c2 = st.columns(2)
            n = c1.slider("Number of questions", 3, 15, 5)
            level = c2.selectbox("Difficulty", ["Easy", "Medium", "Hard"], index=1)
            go = st.form_submit_button("Generate quiz", type="primary")
        if go:
            if not topic.strip():
                st.error("Please enter a topic.")
            else:
                prompt = (f"Create {n} {level.lower()}-level multiple-choice questions on: {topic}. "
                          "Return ONLY a JSON array. Each item: {\"question\": str, \"options\": [4 strings], "
                          "\"answer_index\": int (0-3), \"explanation\": str}.")
                with st.spinner("Creating your quiz…"):
                    text, err = ai_call([{"role": "user", "content": prompt}],
                                        "You write accurate, unambiguous quiz questions.", max_tokens=3500)
                if err:
                    st.error(err)
                else:
                    try:
                        ss.quiz = parse_quiz(text)
                        ss.quiz_topic = topic.strip()
                        ss.quiz_answers = None
                        st.rerun()
                    except Exception:
                        st.error("Could not read the quiz the AI returned. Please try again.")
    elif ss.quiz_answers is None:
        st.subheader(f"Topic: {ss.quiz_topic}")
        with st.form("quiz_form"):
            picks = []
            for i, item in enumerate(ss.quiz):
                picks.append(st.radio(f"**{i + 1}. {item['question']}**", item["options"], index=None, key=f"qz{i}"))
            submitted = st.form_submit_button("Submit answers", type="primary")
        if submitted:
            if None in picks:
                st.warning("Please answer every question.")
            else:
                ss.quiz_answers = picks
                score = sum(1 for it, p in zip(ss.quiz, picks) if it["options"].index(p) == it["answer_index"])
                run("INSERT INTO quiz_results(email, topic, score, total, taken) VALUES(?,?,?,?,?)",
                    (email, ss.quiz_topic, score, len(ss.quiz), datetime.now().isoformat(timespec="minutes")))
                st.rerun()
        if st.button("Cancel quiz"):
            for k in ("quiz", "quiz_answers", "quiz_topic"):
                ss.pop(k, None)
            st.rerun()
    else:
        total = len(ss.quiz)
        score = sum(1 for it, p in zip(ss.quiz, ss.quiz_answers) if it["options"].index(p) == it["answer_index"])
        st.subheader(f"Your score: {score}/{total} ({round(100 * score / total)}%)")
        if score == total:
            st.balloons()
        for i, (it, p) in enumerate(zip(ss.quiz, ss.quiz_answers)):
            ok = it["options"].index(p) == it["answer_index"]
            st.write(f"{'✅' if ok else '❌'} **{i + 1}. {it['question']}**")
            st.write(f"Your answer: {p}" + ("" if ok else f" · Correct: **{it['options'][it['answer_index']]}**"))
            if it["explanation"]:
                st.caption(it["explanation"])
        if st.button("Take another quiz", type="primary"):
            for k in list(ss.keys()):
                if k.startswith("qz") or k in ("quiz", "quiz_answers", "quiz_topic"):
                    ss.pop(k, None)
            st.rerun()

    hist = q("SELECT topic, score, total, taken FROM quiz_results WHERE email=? ORDER BY id DESC LIMIT 20", (email,))
    if hist:
        st.divider()
        st.subheader("Quiz history")
        df = pd.DataFrame(hist)
        df["Percent"] = (100 * df["score"] / df["total"]).round(0)
        st.dataframe(df.rename(columns={"topic": "Topic", "score": "Score", "total": "Out of", "taken": "When"}),
                     hide_index=True, use_container_width=True)


def page_assignments(email):
    st.title("📝 Assignments")
    subs = [s["name"] for s in subjects_of(email)]
    with st.form("add_assignment", clear_on_submit=True):
        title = st.text_input("Title")
        c1, c2, c3 = st.columns(3)
        subject = c1.selectbox("Subject", ["General"] + subs)
        due = c2.date_input("Due date", date.today() + timedelta(days=7))
        prio = c3.selectbox("Priority", PRIORITIES, index=1)
        notes = st.text_area("Notes (optional)", height=70)
        if st.form_submit_button("Add assignment", type="primary") and title.strip():
            run("INSERT INTO assignments(email, title, subject, due, priority, notes) VALUES(?,?,?,?,?,?)",
                (email, title.strip(), subject, due.isoformat(), prio, notes))
            st.rerun()

    flt = st.radio("Show", ["Pending", "In progress", "Done", "All"], horizontal=True)
    sql = "SELECT * FROM assignments WHERE email=?"
    params = [email]
    if flt == "Pending":
        sql += " AND status='Pending'"
    elif flt == "In progress":
        sql += " AND status='In progress'"
    elif flt == "Done":
        sql += " AND status='Done'"
    rows = q(sql + " ORDER BY due", params)
    today = date.today().isoformat()
    if not rows:
        st.info("Nothing here.")
    statuses = ["Pending", "In progress", "Done"]
    for a in rows:
        with st.container(border=True):
            c1, c2, c3 = st.columns([5, 2, 1])
            flag = "🔴 overdue · " if a["status"] != "Done" and a["due"] < today else ""
            c1.markdown(f"**{a['title']}** · {a['subject']}  \n{flag}Due {a['due']} · Priority: {a['priority']}")
            if a["notes"]:
                c1.caption(a["notes"])
            new = c2.selectbox("Status", statuses, index=statuses.index(a["status"]),
                               key=f"as{a['id']}", label_visibility="collapsed")
            if new != a["status"]:
                run("UPDATE assignments SET status=? WHERE id=? AND email=?", (new, a["id"], email))
                st.rerun()
            if c3.button("🗑️", key=f"da{a['id']}"):
                run("DELETE FROM assignments WHERE id=? AND email=?", (a["id"], email))
                st.rerun()


def set_attendance(email, sid, day, status):
    """Save one subject's status for one day. 'No class' removes the record."""
    run("DELETE FROM attendance WHERE email=? AND subject_id=? AND day=?", (email, sid, day))
    if status in ("Present", "Absent"):
        run("INSERT INTO attendance(email, subject_id, day, status) VALUES(?,?,?,?)",
            (email, sid, day, status))


def page_attendance(email):
    st.title("🗓️ Attendance Tracker")
    ss = st.session_state
    ss.setdefault("att_ver", 0)
    if ss.get("att_flash"):
        st.success(ss.pop("att_flash"))

    subs = subjects_of(email)
    if not subs:
        st.info("Add your subjects in **Subjects & Grades** first, then come back to track attendance.")
        return
    names = [s["name"] for s in subs]
    labels = {s["id"]: (s["name"] if names.count(s["name"]) == 1 else f"{s['name']} ({s['id']})") for s in subs}

    target = st.slider("Target attendance %", 50, 95, 75, key="att_target")
    t = target / 100
    summary = attendance_summary(email)
    tot_p = sum(r["Attended"] for r in summary)
    tot_t = sum(r["Total"] for r in summary)
    below = sum(1 for r in summary if r["Total"] and r["Percent"] < target)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Overall attendance", f"{round(100 * tot_p / tot_t, 1)}%" if tot_t else "–")
    m2.metric("Classes attended", tot_p)
    m3.metric("Classes missed", tot_t - tot_p)
    m4.metric("Subjects below target", below)

    tab_mark, tab_sum, tab_month, tab_rec = st.tabs(
        ["✍️ Mark attendance", "📈 Summary", "🗓️ Monthly view", "🧾 Records"])

    # ── Mark attendance for a whole day ──
    with tab_mark:
        d = st.date_input("Date", date.today(), max_value=date.today(), key="att_date")
        day = d.isoformat()
        pretty = d.strftime("%d %b %Y")
        existing = {r["subject_id"]: r["status"]
                    for r in q("SELECT subject_id, status FROM attendance WHERE email=? AND day=?", (email, day))}

        b1, b2, b3 = st.columns(3)
        quick = None
        if b1.button("✅ Mark all Present", use_container_width=True):
            quick = ("Present", f"All subjects marked Present for {pretty}.")
        if b2.button("❌ Mark all Absent", use_container_width=True):
            quick = ("Absent", f"All subjects marked Absent for {pretty}.")
        if b3.button("🧹 Clear this day", use_container_width=True):
            quick = ("No class", f"Cleared attendance for {pretty}.")
        if quick:
            for s in subs:
                set_attendance(email, s["id"], day, quick[0])
            ss.att_ver += 1
            ss.att_flash = quick[1]
            st.rerun()

        st.caption(f"Choose a status for each subject on {pretty}. Use 'No class' for holidays or cancelled classes.")
        options = ["Present", "Absent", "No class"]
        with st.form(f"att_form_{day}_{ss.att_ver}"):
            picks = {}
            for s in subs:
                cur = existing.get(s["id"], "No class")
                picks[s["id"]] = st.radio(labels[s["id"]], options, index=options.index(cur), horizontal=True,
                                          key=f"att_{day}_{s['id']}_{ss.att_ver}")
            saved = st.form_submit_button("💾 Save attendance", type="primary")
        if saved:
            for sid, stt in picks.items():
                set_attendance(email, sid, day, stt)
            ss.att_ver += 1
            ss.att_flash = f"Attendance saved for {pretty}."
            st.rerun()

    # ── Subject-wise summary ──
    with tab_sum:
        if not tot_t:
            st.info("No attendance recorded yet. Mark your first day in the first tab.")
        for r in summary:
            with st.container(border=True):
                c1, c2 = st.columns([2, 3])
                c1.markdown(f"**{labels[r['id']]}**  \n{r['Attended']} attended / {r['Total']} classes")
                c2.progress(min(r["Percent"] / 100, 1.0), text=f"{r['Percent']}%")
                if r["Total"] == 0:
                    c2.caption("No classes recorded yet.")
                elif r["Percent"] >= target:
                    safe = math.floor(r["Attended"] / t - r["Total"])
                    c2.success(f"On track. You can miss {max(safe, 0)} more class(es) and stay at {target}% or above.")
                else:
                    need = math.ceil((t * r["Total"] - r["Attended"]) / (1 - t))
                    c2.error(f"Below target. Attend the next {need} class(es) in a row to reach {target}%.")
        chart = [{"Subject": labels[r["id"]], "Attendance %": r["Percent"]} for r in summary if r["Total"]]
        if chart:
            st.bar_chart(pd.DataFrame(chart).set_index("Subject"))

    # ── Month grid ──
    with tab_month:
        today = date.today()
        c1, c2 = st.columns(2)
        month = c1.selectbox("Month", list(range(1, 13)), index=today.month - 1,
                             format_func=lambda m: calendar.month_name[m])
        year = int(c2.number_input("Year", 2020, 2100, today.year, 1))
        first = date(year, month, 1)
        last = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
        recs = q("SELECT subject_id, day, status FROM attendance WHERE email=? AND day BETWEEN ? AND ?",
                 (email, first.isoformat(), last.isoformat()))
        recs = [r for r in recs if r["subject_id"] in labels]
        if not recs:
            st.info("No attendance recorded in this month.")
        else:
            mp = sum(1 for r in recs if r["status"] == "Present")
            st.metric(f"{calendar.month_name[month]} {year} attendance", f"{round(100 * mp / len(recs), 1)}%",
                      f"{mp} present · {len(recs) - mp} absent", delta_color="off")
            grid = pd.DataFrame("", index=sorted({r["day"] for r in recs}),
                                columns=[labels[s["id"]] for s in subs])
            for r in recs:
                grid.loc[r["day"], labels[r["subject_id"]]] = "✅" if r["status"] == "Present" else "❌"
            grid.index = [datetime.strptime(i, "%Y-%m-%d").strftime("%d %b (%a)") for i in grid.index]
            st.dataframe(grid, use_container_width=True)

    # ── Records ──
    with tab_rec:
        flt = st.selectbox("Subject", ["All"] + [labels[s["id"]] for s in subs])
        inv = {v: k for k, v in labels.items()}
        rows = q("SELECT id, subject_id, day, status FROM attendance WHERE email=? ORDER BY day DESC, id DESC LIMIT 300",
                 (email,))
        rows = [r for r in rows if r["subject_id"] in labels and (flt == "All" or r["subject_id"] == inv[flt])]
        if not rows:
            st.info("No records.")
        for r in rows[:100]:
            c1, c2, c3 = st.columns([5, 1.3, 1.2])
            c1.write(f"{r['day']} · **{labels[r['subject_id']]}** · "
                     f"{'✅' if r['status'] == 'Present' else '❌'} {r['status']}")
            if c2.button("Switch", key=f"sw{r['id']}", help="Flip between Present and Absent"):
                run("UPDATE attendance SET status=? WHERE id=? AND email=?",
                    ("Absent" if r["status"] == "Present" else "Present", r["id"], email))
                ss.att_ver += 1
                st.rerun()
            if c3.button("Delete", key=f"dat{r['id']}"):
                run("DELETE FROM attendance WHERE id=? AND email=?", (r["id"], email))
                ss.att_ver += 1
                st.rerun()


def page_tasks(email):
    st.title("✅ Tasks Todo List")
    with st.form("add_task", clear_on_submit=True):
        c1, c2 = st.columns([4, 1])
        task = c1.text_input("New task")
        prio = c2.selectbox("Priority", PRIORITIES, index=1)
        if st.form_submit_button("Add task", type="primary") and task.strip():
            run("INSERT INTO tasks(email, task, priority, created) VALUES(?,?,?,?)",
                (email, task.strip(), prio, datetime.now().isoformat()))
            st.rerun()

    tasks = q("""SELECT * FROM tasks WHERE email=? ORDER BY done,
                 CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, id""", (email,))
    if not tasks:
        st.info("No tasks yet.")
    for t in tasks:
        c1, c2, c3 = st.columns([0.07, 0.8, 0.13])
        done = c1.checkbox("done", value=bool(t["done"]), key=f"tk{t['id']}", label_visibility="collapsed")
        if done != bool(t["done"]):
            run("UPDATE tasks SET done=? WHERE id=? AND email=?", (int(done), t["id"], email))
            st.rerun()
        label = f"{t['task']}  ·  *{t['priority']}*"
        c2.markdown(f"~~{label}~~" if t["done"] else label)
        if c3.button("Delete", key=f"dt{t['id']}"):
            run("DELETE FROM tasks WHERE id=? AND email=?", (t["id"], email))
            st.rerun()
    if any(t["done"] for t in tasks) and st.button("Clear completed"):
        run("DELETE FROM tasks WHERE email=? AND done=1", (email,))
        st.rerun()


def page_planner(email):
    st.title("📅 Study Planner")
    subs = [s["name"] for s in subjects_of(email)]
    with st.form("add_session", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        d = c1.date_input("Date", date.today())
        start = c2.time_input("Start", time(18, 0))
        end = c3.time_input("End", time(19, 0))
        c4, c5 = st.columns(2)
        subject = c4.selectbox("Subject", ["General"] + subs)
        topic = c5.text_input("Topic / goal")
        if st.form_submit_button("Add session", type="primary"):
            if end <= start:
                st.error("End time must be after start time.")
            else:
                run("INSERT INTO planner(email, day, start, end, subject, topic) VALUES(?,?,?,?,?,?)",
                    (email, d.isoformat(), start.strftime("%H:%M"), end.strftime("%H:%M"), subject, topic))
                st.rerun()

    view = st.radio("View", ["Today", "Next 7 days", "All upcoming"], horizontal=True)
    today = date.today()
    if view == "Today":
        rows = q("SELECT * FROM planner WHERE email=? AND day=? ORDER BY start", (email, today.isoformat()))
    elif view == "Next 7 days":
        rows = q("SELECT * FROM planner WHERE email=? AND day BETWEEN ? AND ? ORDER BY day, start",
                 (email, today.isoformat(), (today + timedelta(days=7)).isoformat()))
    else:
        rows = q("SELECT * FROM planner WHERE email=? AND day>=? ORDER BY day, start", (email, today.isoformat()))
    if not rows:
        st.info("No sessions in this view.")
    for r in rows:
        c1, c2, c3 = st.columns([0.07, 0.8, 0.13])
        done = c1.checkbox("done", value=bool(r["done"]), key=f"pl{r['id']}", label_visibility="collapsed")
        if done != bool(r["done"]):
            run("UPDATE planner SET done=? WHERE id=? AND email=?", (int(done), r["id"], email))
            st.rerun()
        text = f"{r['day']} · {r['start']}–{r['end']} · **{r['subject']}** — {r['topic']}"
        c2.markdown(f"~~{text}~~" if r["done"] else text)
        if c3.button("Delete", key=f"dp{r['id']}"):
            run("DELETE FROM planner WHERE id=? AND email=?", (r["id"], email))
            st.rerun()

    st.divider()
    st.subheader("✨ Get an AI study plan")
    c1, c2 = st.columns(2)
    hours = c1.slider("Hours per day available", 1, 10, 3)
    days = c2.slider("Plan for how many days", 1, 14, 7)
    if st.button("Suggest a plan"):
        pend = q("SELECT title, subject, due FROM assignments WHERE email=? AND status!='Done' ORDER BY due", (email,))
        info = (f"Today is {today.isoformat()}. Subjects: {', '.join(subs) or 'none listed'}. "
                f"Pending assignments: {json.dumps(pend)}. Student profile: {profile_context(email)}. "
                f"Create a realistic {days}-day study timetable with {hours} hours per day, "
                "with short breaks, prioritising nearest deadlines. Use a day-by-day markdown list.")
        with st.spinner("Planning…"):
            text, err = ai_call([{"role": "user", "content": info}], "You are an expert study coach.", 2000)
        st.error(err) if err else st.markdown(text)


# ───────────────────────────── Main ─────────────────────────────
PAGES = {
    "Home": page_home,
    "My Profile": page_profile,
    "AI Assistant Chat": page_chat,
    "Subjects & Grades": page_grades,
    "Concept Quiz": page_quiz,
    "Assignments": page_assignments,
    "Attendance Tracker": page_attendance,
    "Tasks Todo List": page_tasks,
    "Study Planner": page_planner,
}


def main():
    init_db()
    if "user" not in st.session_state:
        auth_screen()
        return
    email = st.session_state.user
    with st.sidebar:
        st.markdown("## 📚 StudyMateAI")
        st.write("Logged in as:")
        st.markdown(f"**{email}**")
        if st.button("Log out"):
            st.session_state.clear()
            st.rerun()
        st.divider()
        choice = st.radio("Navigation Menu", list(PAGES.keys()), index=0)
    PAGES[choice](email)


if __name__ == "__main__":
    main()