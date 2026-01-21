import pandas as pd
import re
import os

# --- CONFIGURATION ---
# Replace with your local file path OR Google Sheets URL
# SOURCE_PATH = 'https://docs.google.com/spreadsheets/d/your-sheet-id/edit#gid=0'
SOURCE_PATH = 'd:/UDEMY/tt_automate/test_dataset.xlsx' 

# List of subjects to look for
MY_SUBJECTS = [
    "Radar", 
    "DIP", 
    "Embedded Lab", 
    "DnM", 
    "WSN"
]
# ---------------------

def get_data_frame(path):
    """
    Loads the DataFrame from a local file or Google Sheets URL.
    """
    print(f"Loading data from: {path}")
    
    if path.startswith("http"):
        # Handle Google Sheets URL
        if "/edit" in path:
            export_url = path.replace("/edit", "/export")
            if "?" in path:
                 # Attempt to keep query params or just force format=xlsx
                 export_url = export_url.split("?")[0] + "?format=xlsx"
            else:
                 export_url += "?format=xlsx"
            print(f"Converted Google Sheet URL to export URL: {export_url}")
            return pd.read_excel(export_url, engine='openpyxl', header=None)
        else:
             # Assume it's a direct link to a file or export link
             return pd.read_excel(path, engine='openpyxl', header=None)
    else:
        # Local file
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found at: {path}")
        return pd.read_excel(path, engine='openpyxl', header=None)

def find_anchor_and_process(df):
    """
    Finds the header row containing 'Classroom No.' and returns a cleaned DataFrame.
    """
    anchor_idx = -1
    
    # Iterate to find the anchor row
    for idx, row in df.iterrows():
        first_col_val = str(row[0]).strip()
        if "Classroom No." in first_col_val:
            anchor_idx = idx
            print(f"Found Anchor 'Classroom No.' at Row {idx + 1}")
            break
            
    if anchor_idx == -1:
        raise ValueError("Could not find 'Classroom No.' in the first column.")

    # Slice the dataframe from the anchor row
    # Set the anchor row as header
    df_cleaned = df.iloc[anchor_idx:].copy()
    
    # Promote the first row to be the header
    new_header = df_cleaned.iloc[0]
    df_cleaned = df_cleaned[1:] # Take the data below header
    df_cleaned.columns = new_header # Set the header
    
    # Reset index
    df_cleaned.reset_index(drop=True, inplace=True)
    
    return df_cleaned

def extract_timetable(df, subjects):
    """
    Extracts classes matching the subjects.
    """
    results = []
    
    # 1. Handle Merged Cells
    # 'Classroom No.' and 'Days' often have merged cells (NaN in pandas)
    # Forward fill to propagate the values down
    # Assuming Column 0 is Room and Column 1 is Day
    
    # Rename columns to standard names for easier access if they match expectation
    # But rely on index to be safe as column names might vary slightly
    
    # ffill the first two columns
    df.iloc[:, 0] = df.iloc[:, 0].ffill()
    df.iloc[:, 1] = df.iloc[:, 1].ffill()
    
    # Identify Time Slot Columns
    # Usually starting from Column 3? 
    # Let's inspect headers to filter out non-time headers if needed
    # But iterating all is safer unless there's junk.
    
    print("Processing timetable...")
    
    total_rows = len(df)
    
    for idx, row in df.iterrows():
        room = row.iloc[0]
        day = row.iloc[1]
        
        # Skip if Room or Day is missing (though ffill should handle it, valid data check)
        if pd.isna(room) or pd.isna(day):
            continue
            
        # Iterate through all other columns (Time Slots)
        # We start from column index 2 or 3. 
        # In the sample CSV: 
        # Col 0: Room, Col 1: Day, Col 2: Empty/Junk, Col 3: 8:00...
        # We'll check all remaining columns.
        
        for col_idx in range(2, len(df.columns)):
            cell_value = str(row.iloc[col_idx])
            time_slot = df.columns[col_idx]
            
            # Skip empty cells
            if cell_value.strip() == "" or cell_value.lower() == "nan":
                continue
                
            # Check for Subject Match
            # We match if ANY of the user's subjects are present in the cell content
            # Case-insensitive
            
            for subject in subjects:
                # Use regex with word boundaries to avoid partial matches (e.g. "DIP" matching "Dipti")
                # re.escape handles special characters in subject names
                pattern = rf"\b{re.escape(subject)}\b"
                if re.search(pattern, cell_value, re.IGNORECASE):
                    # clean up the cell value (remove newlines)
                    clean_cell = cell_value.replace("\n", " ").strip()
                    
                    results.append({
                        "Day": day,
                        "Time": time_slot,
                        "Room": room,
                        "Subject": subject, 
                        "Full Detail": clean_cell
                    })
                    break # Avoid adding same class twice if multiple keywords match
                    
    return results

def main():
    try:
        # Load
        df = get_data_frame(SOURCE_PATH)
        
        # Process Header
        df_clean = find_anchor_and_process(df)
        
        # Extract
        timetable = extract_timetable(df_clean, MY_SUBJECTS)
        
        # Output
        if timetable:
            out_df = pd.DataFrame(timetable)
            output_file = "my_timetable.csv"
            out_df.to_csv(output_file, index=False)
            print(f"Success! Found {len(timetable)} classes. Saved to {output_file}")
            print(out_df.head())
        else:
            print("No classes found matching your subjects.")
            
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
