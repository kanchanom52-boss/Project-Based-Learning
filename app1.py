import streamlit as st
import hashlib
import re
from datetime import date

# ---------- INITIAL LAYOUT SELECTION ----------
if "logged_in" in st.session_state and st.session_state["logged_in"] is not None:
    layout_mode = "wide"
else:
    layout_mode = "centered"

st.set_page_config(
    page_title="StudyMate AI",
    page_icon="🎓",
    layout=layout_mode
)

# ---------- SESSION DATA INITIALIZATION ----------
defaults = {
    "users": {},
    "logged_in": None,
    "page": "Login",
    "subjects": [],
    "tasks": [],
    "assignments": [],
    "attendance": {},
    "marks": {},
    "study_goal": 3,
    "study_done": 0.0,
    "quiz_score": None,
    "chat_history": [{"role": "assistant", "content": "Hello! I am your StudyMate AI assistant. How can I help you with your studies today?"}]
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


# ---------- COMMON HEADER ----------
st.title("🎓 StudyMate AI")
st.caption("Your personalized companion for continuous learning and smart scheduling")
st.divider()


# ---------- AUTHENTICATION TIMELINE ROUTING ----------
if st.session_state.logged_in is None:

    choice = st.radio(
        "Choose an option",
        ["Login", "Create Account"],
        horizontal=True,
        key="auth_choice"
    )

    if choice == "Create Account":
        st.subheader("📝 Create Account")

        with st.form("register_form"):
            email_input = st.text_input("Email address").strip().lower()
            pass_input = st.text_input("Create password", type="password")
            confirm_input = st.text_input("Confirm password", type="password")
            submit = st.form_submit_button("Create Account", use_container_width=True)

        if submit:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email_input):
                st.error("Enter a valid email address.")
            elif len(pass_input) < 8:
                st.error("Password must be at least 8 characters long.")
            elif pass_input != confirm_input:
                st.error("Passwords do not match.")
            elif email_input in st.session_state.users:
                st.error("An account with this email address already exists.")
            else:
                st.session_state.users[email_input] = {
                    "password": hash_password(pass_input),
                    "name": "",
                    "college": "",
                    "course": "",
                    "year": "First Year",
                }
                st.success("Account created successfully! Select Login above to continue.")

    else:
        st.subheader("🔐 Sign In")

        with st.form("login_form"):
            email_input = st.text_input("Email address").strip().lower()
            pass_input = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login", use_container_width=True)

        if submit:
            user_data = st.session_state.users.get(email_input)
            if user_data and user_data["password"] == hash_password(pass_input):
                st.session_state.logged_in = email_input
                st.rerun()
            else:
                st.error("Invalid credentials. Please double check email/password or create an account.")

        with st.expander("Forgot Password?"):
            st.info("Email recovery simulations are currently under planned optimization.")


# ---------- IN-APP SECURE DASHBOARD MODULES ----------
else:
    current_user_email = st.session_state.logged_in
    user_profile = st.session_state.users[current_user_email]

    with st.sidebar:
        st.title("📚 StudyMate")
        st.write(f"Logged in as: **{current_user_email}**")
        st.divider()

        nav_page = st.radio(
            "Navigation Menu",
            [
                "Home",
                "My Profile",
                "AI Assistant Chat",
                "Subjects & Grades",
                "Concept Quiz",
                "Assignments",
                "Attendance Ledger",
                "Tasks Todo List",
                "Study Planner",
            ],
        )

        st.divider()
        if st.button("Logout Dashboard", use_container_width=True):
            st.session_state.logged_in = None
            st.rerun()

    # ---------- HOME DISPLAY MODULE ----------
    if nav_page == "Home":
        student_name = user_profile.get("name") or "Student"
        st.header(f"Welcome Back, {student_name}! 👋")
        st.write("Here is your holistic look into current academic operations:")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Subjects Added", len(st.session_state.subjects))
        c2.metric("Assignments Tracked", len(st.session_state.assignments))
        c3.metric("Pending Checklist Tasks", sum(not task["done"] for task in st.session_state.tasks))

        attendance_values = [
            item["attended"] / item["total"] * 100
            for item in st.session_state.attendance.values()
            if item["total"] > 0
        ]
        average_attendance = (sum(attendance_values) / len(attendance_values) if attendance_values else 0.0)
        c4.metric("Avg Attendance Percentage", f"{average_attendance:.1f}%")

        st.divider()
        st.subheader("🎯 Daily Goal Tracker")
        
        progress_calc = min(st.session_state.study_done / max(st.session_state.study_goal, 1), 1.0)
        st.progress(progress_calc)
        st.write(f"Studied today: **{st.session_state.study_done:g} hours** out of **{st.session_state.study_goal} hours** target.")

        if st.session_state.subjects:
            st.info(f"**Enrolled Modules:** {', '.join(st.session_state.subjects)}")
        else:
            st.warning("No subjects added yet. Navigate to 'Subjects & Grades' to begin.")

    # ---------- EDIT PROFILE MODULE ----------
    elif nav_page == "My Profile":
        st.header("👤 Edit Profile Summary")
        st.write(f"Account Profile Email: `{current_user_email}`")

        with st.form("profile_form"):
            form_name = st.text_input("Full Name", value=user_profile.get("name", ""))
            form_college = st.text_input("College / University", value=user_profile.get("college", ""))
            form_course = st.text_input("Course / Branch", value=user_profile.get("course", ""))
            year_options = ["First Year", "Second Year", "Third Year", "Final Year"]
            
            saved_year = user_profile.get("year", "First Year")
            default_year_idx = year_options.index(saved_year) if saved_year in year_options else 0
            
            form_year = st.selectbox("Current Year", year_options, index=default_year_idx)
            save_action = st.form_submit_button("Update Profile Details", use_container_width=True)

        if save_action:
            if not form_name.strip():
                st.error("Please enter a valid full name.")
            else:
                user_profile.update({
                    "name": form_name.strip(),
                    "college": form_college.strip(),
                    "course": form_course.strip(),
                    "year": form_year,
                })
                st.success("Profile saved successfully!")
                st.rerun()

    # ---------- AI CHATBOX WORKSPACE MODULE ----------
    elif nav_page == "AI Assistant Chat":
        st.header("🧠 StudyMate AI Conversational Engine")
        st.caption("Ask questions, test parameters, or get personalized revision techniques.")

        # Render complete history logs dynamically
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # Accept interactive chat input streams
        if prompt := st.chat_input("Ask me anything about your courses..."):
            with st.chat_message("user"):
                st.markdown(prompt)
            st.session_state.chat_history.append({"role": "user", "content": prompt})

            # Automated local responses generated mock-up logic mapping context entries
            response = f"I've noted your question regarding '{prompt}'. As your personal assistant, I suggest checking your recorded homework tasks or testing your skills on the 'Concept Quiz' tab to solidify this topic!"
            
            with st.chat_message("assistant"):
                st.markdown(response)
            st.session_state.chat_history.append({"role": "assistant", "content": response})

    # ---------- SUBJECTS & GRADES CONFIGURATION ----------
    elif nav_page == "Subjects & Grades":
        st.header("📘 Module Registration & Grades Management")

        with st.form("subject_form"):
            subject_input = st.text_input("Enter New Subject Name", placeholder="e.g., Data Structures")
            add_action = st.form_submit_button("Register Module", use_container_width=True)

        if add_action:
            cleaned_sub = subject_input.strip()
            if cleaned_sub and cleaned_sub not in st.session_state.subjects:
                st.session_state.subjects.append(cleaned_sub)
                st.session_state.attendance[cleaned_sub] = {"attended": 0, "total": 0}
                st.success(f"Registered module: {cleaned_sub}")
                st.rerun()
            elif cleaned_sub:
                st.warning("This subject entry item already exists inside the active timeline list.")

        if st.session_state.subjects:
            st.subheader("Active Modules Registered")
            for sub_item in st.session_state.subjects:
                left_col, right_col = st.columns([5, 1])
                left_col.write(f"📘 {sub_item}")
                if right_col.button("Remove", key=f"rm_sub_{sub_item}"):
                    st.session_state.subjects.remove(sub_item)
