"""
Core timetable extraction logic extracted from Streamlit app
"""
import pandas as pd
import re
import json
import os
from io import BytesIO
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# File paths (in parent directory)
CLASS_TT_PATH = r"../TT - even sem 2025-2026.xlsx - Class Occupancy-even sem final.xlsx"
LAB_TT_PATH = r"../TT - even sem 2025-2026.xlsx - Lab Occupancy-even sem final.csv"

def pre_clean_values(raw_values):
    """Filters out obvious non-subjects using Regex before sending to AI."""
    cleaned_set = set()
    time_pattern = re.compile(r'\d{1,2}[:.]\d{2}')
    room_pattern = re.compile(r'^(CR-|Hall|Lab|Auditorium)', re.IGNORECASE)
    ignore_keywords = [
        "institute", "time table", "session", "semester", "branch", 
        "section", "break", "first half", "second half", "mr.", "ms.", "dr."
    ]

    for val in raw_values:
        sub_vals = str(val).split('/')
        for sv in sub_vals:
            v = sv.strip()
            v_lower = v.lower()
            if len(v) < 2: continue
            if time_pattern.search(v) and "-" in v: continue
            if room_pattern.match(v): continue
            if any(x in v_lower for x in ignore_keywords): continue
            cleaned_set.add(v)
    return sorted(list(cleaned_set))

def get_groq_mapping(raw_values, api_key, model):
    """Uses Groq API to group raw subject strings into clean, unique subject names."""
    client = Groq(api_key=api_key)
    
    # Limit input to prevent token overflow (max ~100 unique values)
    limited_values = raw_values[:100] if len(raw_values) > 100 else raw_values
    values_str = "\n".join([f"- {v}" for v in limited_values])
    
    prompt = f"""
    You are a data cleaning assistant. I will give you a list of strings from a timetable.
    
    Your Goal: Extract the CLEAN SUBJECT CODE/NAME and group variations.
    
    RULES FOR CLEANING:
    1. **THE "FIRST WORD" RULE**: The Subject is almost always the **FIRST WORD** of the string.
       - Delimiters: Space, Hyphen (-), Parenthesis, Newline.
       - Example: "DIP-TJ" -> "DIP", "Radar (301)" -> "Radar", "DnM\\nSD" -> "DnM".
    2. **HANDLING SLASHes (/)**: If a string contains '/', it means TWO subjects. Use the "First Word" rule for each part.
       - "DIP-TJ / FML-ND" -> "DIP" and "FML".
    3. REMOVE FACULTY/ROOMS: "Dr.", "Mr.", "(301)", "CR-2" are NOT subjects.
    4. EXCLUDE JUNK: "Branch", "Semester", "Lunch".
    
    Output Format:
    JSON Object {{"Clean_Subject_Name": ["original_string_1", "original_string_2"]}}
    
    Raw Values to Process:
    {values_str}
    """

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=4000,  # Reduced to be safer
            response_format={"type": "json_object"}
        )
        content = completion.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"Groq API Error: {e}")
        # Fallback: create identity mapping for limited set
        result = {}
        for val in limited_values:
            # Use first word as key
            first_word = re.split(r'[\s\-\n(]+', val)[0].strip()
            if first_word:
                if first_word not in result:
                    result[first_word] = []
                result[first_word].append(val)
        return result

def process_file_data(filepath, anchor_text):
    """Generic processor: Load -> Find Anchor -> Clean -> Info"""
    if not os.path.exists(filepath):
        return None
        
    try:
        # Load
        try:
            df_raw = pd.read_excel(filepath, engine='openpyxl', header=None)
        except Exception:
            df_raw = pd.read_csv(filepath, header=None)
        
        # Find Anchor
        anchor_idx = -1
        for idx, row in df_raw.iterrows():
            if anchor_text in str(row.values): 
                anchor_idx = idx
                break
            if anchor_idx == -1 and anchor_text in str(row[0]):
                anchor_idx = idx
                break
        
        if anchor_idx == -1:
            return None
        
        # Slice & Header
        df_cleaned = df_raw.iloc[anchor_idx:].copy()
        new_header = df_cleaned.iloc[0]
        df_cleaned = df_cleaned[1:]
        df_cleaned.columns = new_header
        df_cleaned.reset_index(drop=True, inplace=True)
        
        # Fill Merged
        cols_to_fill = [c for c in df_cleaned.columns if "Classroom" in str(c) or "Lab Name" in str(c) or "Day" in str(c)]
        if cols_to_fill:
            df_cleaned[cols_to_fill] = df_cleaned[cols_to_fill].ffill()
        else:
            df_cleaned.iloc[:, 0:2] = df_cleaned.iloc[:, 0:2].ffill()
        
        # Time Columns
        time_col_indices = []
        time_pattern = re.compile(r'\d{1,2}[:.]\d{2}') 
        for idx, col_name in enumerate(df_cleaned.columns):
            if time_pattern.search(str(col_name)):
                time_col_indices.append(idx)
        
        if not time_col_indices:
            return None

        # Extract Raw Unique Values
        unique_raw_values = set()
        for col_idx in time_col_indices:
            vals = df_cleaned.iloc[:, col_idx].dropna().unique()
            for v in vals:
                v_str = str(v).strip()
                if v_str and v_str.lower() != "nan":
                    unique_raw_values.add(v_str)
                    
        return df_cleaned, time_col_indices, unique_raw_values

    except Exception as e:
        print(f"Error processing file: {e}")
        return None

def extract_timetable(selected_subjects, subject_mapping, branch="", batch=""):
    """Main extraction logic"""
    # Process files
    class_data = process_file_data(CLASS_TT_PATH, "Classroom No.")
    lab_data = process_file_data(LAB_TT_PATH, "Lab Name/ No.")
    
    # Handle 2-hour lab duration
    if lab_data:
        df_lab, t_cols, _ = lab_data
        df_lab.iloc[:, t_cols] = df_lab.iloc[:, t_cols].ffill(axis=1, limit=1)
        lab_data = (df_lab, t_cols, lab_data[2])
    
    results = []
    
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
                
                parts = cell_val.split('/')
                for part in parts:
                    part = part.strip()
                    if not part: continue
                    
                    # Student Filter (Lab Only) - Keep branch filter, remove batch filter
                    if source_type == "Lab":
                        if branch and branch.lower() not in part.lower():
                            continue

                    # Hybrid Match
                    display_subj = None
                    
                    if part in valid_raw_s:
                        for sel in selected_subjects:
                            if part in mapping[sel]:
                                display_subj = sel
                                break
                                
                    if not display_subj:
                        first_word = re.split(r'[\s\-\n(]+', part)[0].strip()
                        for sel in selected_subjects:
                            if first_word.lower() == sel.lower():
                                display_subj = sel
                                break
                                
                    if display_subj:
                        specific_room = room_default
                        if source_type == "Class":
                            room_match = re.search(r'\(([^)]+)\)$', part)
                            if room_match:
                                specific_room = room_match.group(1).strip()
                        
                        # Normalize Time Label
                        norm_time = time_label
                        try:
                            first_part = re.split(r'[-–]', str(time_label))[0].strip()
                            val = float(first_part.replace(':', '.')[:5])
                            if 1.00 <= val < 7.00: val += 12.00
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
        
    # Extract
    if class_data:
        results += extract_from_df(class_data[0], class_data[1], valid_raw, subject_mapping, "Class")
    if lab_data:
        results += extract_from_df(lab_data[0], lab_data[1], valid_raw, subject_mapping, "Lab")
        
    if not results:
        return None
        
    # Post-process
    out_df = pd.DataFrame(results)
    out_df['Cell Content'] = out_df['Subject'] + " (" + out_df['Room'] + ")"
    
    # Normalize Days
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
    
    # Pivot & Dedupe
    def unique_join(x):
        return ' | '.join(sorted(list(set(x))))

    pivot_df = out_df.pivot_table(
        index='Day', 
        columns='Time', 
        values='Cell Content', 
        aggfunc=unique_join
    )
    
    pivot_df = pivot_df.sort_index()
    
    # Sort Time Columns
    def parse_time(t_str):
        try:
            first_part = re.split(r'[-–]', str(t_str))[0].strip()
            val = float(first_part.replace(':', '.'))
            if 1.00 <= val < 7.00: val += 12.00
            return val
        except: return 99.0
    
    sorted_cols = sorted(pivot_df.columns.tolist(), key=parse_time)
    pivot_df = pivot_df[sorted_cols]
    
    return pivot_df.to_dict()
