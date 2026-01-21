import streamlit as st
import pandas as pd
import requests
import re
import os
import json
from io import BytesIO
from groq import Groq
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# --- PAGE CONFIG ---
st.set_page_config(page_title="Uni Timetable Extractor", layout="wide")

st.title("📅 Unified Timetable Extractor (Class + Lab)")
st.markdown("Upload your **Class Timetable** and/or **Lab Occupancy** sheets. The AI will merge them into a single master schedule.")

# --- HELPER FUNCTIONS ---

def get_google_sheet_content(url):
    """Smarter URL handler for Google Sheets."""
    if "docs.google.com" not in url:
        return None
        
    if "/edit" in url:
        export_url = url.replace("/edit", "/export")
        if "?" in url:
            export_url = export_url.split("?")[0] + "?format=xlsx"
        else:
            export_url += "?format=xlsx"
            
    elif "/pubhtml" in url:
        # Published sheets often fail with .xlsx, force CSV
        base = url.split("/pubhtml")[0]
        # Check for GID
        gid_match = re.search(r'gid=(\d+)', url)
        gid_param = f"&gid={gid_match.group(1)}" if gid_match else ""
        export_url = f"{base}/pub?output=csv{gid_param}"
        
    else:
        export_url = url

    try:
        response = requests.get(export_url)
        if response.status_code == 200:
            return BytesIO(response.content)
        else:
            st.error(f"Failed to fetch {url}. Status: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Error fetching URL: {e}")
        return None

def pre_clean_values(raw_values):
    """
    Filters out obvious non-subjects using Regex before sending to AI.
    """
    cleaned_set = set()
    
    # Patterns to IGNORE
    time_pattern = re.compile(r'\d{1,2}[:.]\d{2}') # Matches 10.00, 9:30
    room_pattern = re.compile(r'^(CR-|Hall|Lab|Auditorium)', re.IGNORECASE)
    
    ignore_keywords = [
        "institute", "time table", "session", "semester", "branch", 
        "section", "break", "first half", "second half", "mr.", "ms.", "dr."
    ]

    for val in raw_values:
        # Handle multiple subjects in one cell separated by '/'
        # e.g. "DIP-TJ(301) / FML-ND(002)"
        sub_vals = str(val).split('/')
        
        for sv in sub_vals:
            v = sv.strip()
            v_lower = v.lower()
            
            # 1. Skip Short/Empty
            if len(v) < 2: continue
            
            # 2. Skip Time Slots (e.g., "10.00-11.00")
            if time_pattern.search(v) and "-" in v: continue
            
            # 3. Skip Room Numbers (e.g., "CR-102")
            if room_pattern.match(v): continue
            
            # 4. Skip Metadata Headers
            if any(x in v_lower for x in ignore_keywords): continue
            
            cleaned_set.add(v)
        
    return sorted(list(cleaned_set))

@st.cache_data(show_spinner=False)
def get_groq_mapping(raw_values, api_key, model):
    """
    Uses Groq API to group raw subject strings into clean, unique subject names.
    Returns: dict { "Clean Subject Name": ["raw_1", "raw_2"] }
    """
    client = Groq(api_key=api_key)
    
    # Prepare the list for prompt
    values_str = "\n".join([f"- {v}" for v in raw_values])
    
    prompt = f"""
    You are a data cleaning assistant. I will give you a list of strings from a timetable.
    
    Your Goal: Extract the CLEAN SUBJECT CODE/NAME and group variations.
    
    RULES FOR CLEANING:
    1. **THE "FIRST WORD" RULE**: The Subject is almost always the **FIRST WORD** of the string.
       - Delimiters: Space, Hyphen (-), Parenthesis, Newline.
       - Example: "DIP-TJ" -> "DIP", "Radar (301)" -> "Radar", "DnM\nSD" -> "DnM".
    2. **HANDLING SLASHes (/)**: If a string contains '/', it means TWO subjects. Use the "First Word" rule for each part.
       - "DIP-TJ / FML-ND" -> "DIP" and "FML".
    3. REMOVE FACULTY/ROOMS: "Dr.", "Mr.", "(301)", "CR-2" are NOT subjects.
    4. EXCLUDE JUNK: "Branch", "Semester", "Lunch".
    
    Output Format:
    JSON Object {{"Clean_Subject_Name": ["original_string_1", "original_string_2"]}}
    
    Raw Values to Process:
    {values_str}
    """
    
    # LOGGING THE PROMPT FOR DEBUGGING
    try:
        with open("last_groq_prompt.txt", "w", encoding="utf-8") as f:
            f.write(prompt)
    except Exception as e:
        print(f"Failed to log prompt: {e}")

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )
        content = completion.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        st.error(f"Groq API Error: {e}")
        return None

def process_file_data(uploaded_file, anchor_text):
    """
    Generic processor: Load -> Find Anchor -> Clean -> Info
    Returns: (df_cleaned, time_col_indices, unique_raw_values) or None
    """
    if not uploaded_file:
        return None
        
    try:
        # Load (Try Excel first, then CSV)
        try:
            df_raw = pd.read_excel(uploaded_file, engine='openpyxl', header=None)
        except Exception:
            uploaded_file.seek(0)
            df_raw = pd.read_csv(uploaded_file, header=None)
        
        # 1. Anchor Detection
        anchor_idx = -1
        for idx, row in df_raw.iterrows():
            if anchor_text in str(row.values): 
                anchor_idx = idx
                break
            if anchor_idx == -1 and anchor_text in str(row[0]):
                anchor_idx = idx
                break
        
        if anchor_idx == -1:
            st.error(f"Anchor '{anchor_text}' not found in file.")
            return None
        
        # 2. Slice & Header
        df_cleaned = df_raw.iloc[anchor_idx:].copy()
        new_header = df_cleaned.iloc[0]
        df_cleaned = df_cleaned[1:]
        df_cleaned.columns = new_header
        df_cleaned.reset_index(drop=True, inplace=True)
        
        # 3. Fill Merged
        cols_to_fill = [c for c in df_cleaned.columns if "Classroom" in str(c) or "Lab Name" in str(c) or "Day" in str(c)]
        if cols_to_fill:
            df_cleaned[cols_to_fill] = df_cleaned[cols_to_fill].ffill()
        else:
            df_cleaned.iloc[:, 0:2] = df_cleaned.iloc[:, 0:2].ffill()
        
        # 4. Time Columns
        time_col_indices = []
        time_pattern = re.compile(r'\d{1,2}[:.]\d{2}') 
        for idx, col_name in enumerate(df_cleaned.columns):
            if time_pattern.search(str(col_name)):
                time_col_indices.append(idx)
        
        if not time_col_indices:
            st.error("No time columns found.")
            return None

        # 5. Extract Raw Unique Values
        unique_raw_values = set()
        for col_idx in time_col_indices:
            vals = df_cleaned.iloc[:, col_idx].dropna().unique()
            for v in vals:
                v_str = str(v).strip()
                if v_str and v_str.lower() != "nan":
                    unique_raw_values.add(v_str)
                    
        return df_cleaned, time_col_indices, unique_raw_values

    except Exception as e:
        st.error(f"Error processing file: {e}")
        return None

# --- CONFIGURATION (UNIVERSITY STANDARD) ---
# Local Files stored in Backend
CLASS_TT_PATH = r"TT - even sem 2025-2026.xlsx - Class Occupancy-even sem final.xlsx"
LAB_TT_PATH = r"TT - even sem 2025-2026.xlsx - Lab Occupancy-even sem final.csv"

# --- SIDEBAR: STATUS ---
st.sidebar.header("1. Data Status")

# Function to load local data
def load_local_data(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "rb") as f:
            return BytesIO(f.read())
    except:
        return None

# Load Class Data
class_file = load_local_data(CLASS_TT_PATH)
if class_file:
    st.sidebar.success("✅ Class Timetable: Loaded")
else:
    st.sidebar.error(f"❌ Class File Missing: {CLASS_TT_PATH}")

# Load Lab Data
lab_file = load_local_data(LAB_TT_PATH)
if lab_file:
    st.sidebar.success("✅ Lab Occupancy: Loaded")
else:
    st.sidebar.error(f"❌ Lab File Missing: {LAB_TT_PATH}")

# STUDENT FILTERS
st.sidebar.header("2. Student Details")
branch_input = st.sidebar.text_input("Branch (e.g. ECE, CSE)", help="Filter Labs by Branch").strip()
batch_input = st.sidebar.text_input("Batch (e.g. A1, B2)", help="Filter Labs by Batch").strip()

# GROQ CONFIG
st.sidebar.header("3. AI Configuration")
env_key = os.getenv("GROQ_API_KEY")
if env_key and not env_key.startswith("gsk_..."):
    groq_api_key = env_key
    st.sidebar.success("✅ AI Key loaded")
else:
    groq_api_key = st.sidebar.text_input("Groq API Key", type="password")

model_name = st.sidebar.selectbox("Model", ["qwen/qwen3-32b", "openai/gpt-oss-120b"], index=1)

# --- MAIN LOGIC ---

# Process Inputs
class_data = None
lab_data = None

if class_file:
    with st.spinner("Processing Class Data..."):
        class_data = process_file_data(class_file, "Classroom No.")

if lab_file:
    with st.spinner("Processing Lab Data..."):
        lab_data = process_file_data(lab_file, "Lab Name/ No.")
        # LAB SPECIFIC: Handle 2-Hour Duration (Horizontal Fill)
        if lab_data:
            df_lab, t_cols, _ = lab_data
            # Apply horizontal ffill to time columns to handle merged cells (2hr labs)
            # We must be careful not to fill across days, but rows are Days. 
            # We only fill across time columns.
            
            # Select proper time columns using iloc
            # Pandas ffill(axis=1) works on the whole selection
            # We limit=1 because user said "always 2 hours"
            df_lab.iloc[:, t_cols] = df_lab.iloc[:, t_cols].ffill(axis=1, limit=1)
            
            # Update tuple
            lab_data = (df_lab, t_cols, lab_data[2])

if not class_data and not lab_data:
    st.warning("Please upload at least one timetable source.")
    st.stop()

# Combine Raw Values
all_raw_values = set()
if class_data:
    all_raw_values.update(class_data[2])
    
# User Change: Do NOT add Lab Data to the AI Refinement List.
# if lab_data: all_raw_values.update(lab_data[2])

sorted_raw = sorted(list(all_raw_values))

# Smart Mapping
subject_mapping = {}
use_ai = False

if groq_api_key:
    st.sidebar.divider()
    if st.sidebar.button("✨ Refine Subjects with AI"):
        filtered_raw = pre_clean_values(sorted_raw)
        with st.spinner(f"Analyzing {len(filtered_raw)} unique raw values..."):
            ai_mapping = get_groq_mapping(filtered_raw, groq_api_key, model_name)
            if ai_mapping:
                st.session_state['ai_mapping_dual'] = ai_mapping
                st.session_state['use_ai_dual'] = True
                st.success("Subjects Refined!")

    if st.session_state.get('use_ai_dual'):
        subject_mapping = st.session_state['ai_mapping_dual']
        use_ai = True

if not use_ai:
    for s in sorted_raw:
        clean = s.replace("\n", " ").strip()
        subject_mapping[clean] = [s]

# Selection
st.sidebar.header("3. Select Subjects")
options = sorted(list(subject_mapping.keys()))
selected_subjects = st.sidebar.multiselect("Subjects", options=options)

if st.sidebar.button("Generate Unified Timetable"):
    if not selected_subjects:
        st.error("Select subjects first!")
    else:
        results = []
        
        # Helper extraction extraction (Renamed for clarity)
        def extract_from_df(df, time_cols, valid_raw_s, mapping, source_type):
            extracted = []
            room_col_idx, day_col_idx = 0, 1
            
            for r_idx, row in df.iterrows():
                room_default = str(row.iloc[room_col_idx]).strip()
                day = row.iloc[day_col_idx]
                
                if pd.isna(room_default) or pd.isna(day): continue
                
                for col_idx in time_cols:
                    cell_val = str(row.iloc[col_idx]).strip()
                    time_label = df.columns[col_idx]
                    
                    if not cell_val or cell_val.lower() == "nan": continue
                    
                    # Split '/'
                    parts = cell_val.split('/')
                    for part in parts:
                        part = part.strip()
                        if not part: continue
                        
                        # --- STUDENT FILTER (LAB ONLY) ---
                        if source_type == "Lab":
                            # Check Branch (Case Insensitive)
                            if branch_input and branch_input.lower() not in part.lower():
                                continue
                            # Check Batch
                            if batch_input and batch_input.lower() not in part.lower():
                                continue

                        # Hybrid Match
                        display_subj = None
                        
                        # 1. Exact Input Match
                        if part in valid_raw_s:
                            for sel in selected_subjects:
                                if part in mapping[sel]:
                                    display_subj = sel
                                    break
                                    
                        # 2. First Word Heuristic
                        if not display_subj:
                            first_word = re.split(r'[\s\-\n(]+', part)[0].strip()
                            for sel in selected_subjects:
                                if first_word.lower() == sel.lower():
                                    display_subj = sel
                                    break
                                    
                        if display_subj:
                            # 3. Room Detection
                            # For Lab: Room is the Lab header (room_default)
                            # For Class: Room might be in brackets
                            
                            specific_room = room_default
                            if source_type == "Class":
                                room_match = re.search(r'\(([^)]+)\)$', part)
                                if room_match:
                                    specific_room = room_match.group(1).strip()
                            
                            # 4. Normalize Time Label (Merge 4 PM and 16:00)
                            # Re-using the logic: 1-7 means PM (13-19)
                            norm_time = time_label
                            try:
                                first_part = re.split(r'[-–]', str(time_label))[0].strip()
                                val = float(first_part.replace(':', '.')[:5]) # take first few chars safe
                                if 1.00 <= val < 7.00: val += 12.00
                                # Format: "16:00 - 17:00"
                                norm_time = f"{int(val):02d}:00 - {int(val)+1:02d}:00"
                            except:
                                pass
                                
                            extracted.append({
                                "Day": day,
                                "Time": norm_time,
                                "Subject": display_subj,
                                "Room": specific_room
                            })
            return extracted

        # Build valid set
        valid_raw = set()
        for sel in selected_subjects:
            valid_raw.update(subject_mapping[sel])
            
        # Extract CLASS
        if class_data:
            results += extract_from_df(class_data[0], class_data[1], valid_raw, subject_mapping, "Class")
            
        # Extract LAB
        if lab_data:
            results += extract_from_df(lab_data[0], lab_data[1], valid_raw, subject_mapping, "Lab")
            
        if results:
            out_df = pd.DataFrame(results)
            
            # --- POST PROCESSING (Dedupe, Sort, Pivot) ---
            
            # 1. Create Display Content
            out_df['Cell Content'] = out_df['Subject'] + " (" + out_df['Room'] + ")"
            
            # 2. Normalize Days
            day_map = {
                "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", 
                "fri": "Friday", "sat": "Saturday", "sun": "Sunday"
            }
            def clean_day(d):
                d = str(d).lower()
                for k,v in day_map.items():
                    if k in d: return v
                return d.title()
            out_df['Day'] = out_df['Day'].apply(clean_day)
            
            days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            out_df['Day'] = pd.Categorical(out_df['Day'], categories=days_order, ordered=True)
            
            # 3. Sort Time
            def parse_time(t_str):
                try:
                    first_part = re.split(r'[-–]', str(t_str))[0].strip()
                    val = float(first_part.replace(':', '.'))
                    if 1.00 <= val < 7.00: val += 12.00
                    return val
                except: return 99.0
            
            # 4. Pivot & Dedupe
            def unique_join(x):
                return ' | '.join(sorted(list(set(x))))

            pivot_df = out_df.pivot_table(
                index='Day', 
                columns='Time', 
                values='Cell Content', 
                aggfunc=unique_join
            )
            
            pivot_df = pivot_df.sort_index()
            
            # Reorder Time Columns
            sorted_cols = sorted(pivot_df.columns.tolist(), key=parse_time)
            pivot_df = pivot_df[sorted_cols]
            
            st.success(f"Generated Unified Timetable with {len(results)} entries!")
            st.dataframe(pivot_df, use_container_width=True)
            
            csv = pivot_df.to_csv().encode('utf-8')
            st.download_button("Download Unified Grid (CSV)", csv, "unified_timetable.csv", "text/csv")
            
        else:
            st.info("No matching classes found in the provided files.")
