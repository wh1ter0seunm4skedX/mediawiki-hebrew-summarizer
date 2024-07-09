import os
from operations.logs import log_action
from operations.read_operations import get_mediawiki_base_url
from utils.text_processing import parse_database_text, parse_wikitext_to_clean_text, extract_text_between_big_tags
from utils.database_utils import create_connection, close_connection, config
from mysql.connector import Error
from datetime import datetime


def import_csv_to_raw_page_data(user, dir_path):
    """Import data from the newest CSV file in the directory into the raw_page_data table and log the operation."""
    target_db = config['database']
    try:
        conn = create_connection(target_db, allow_local_infile=True)
        if not conn:
            print(f"Failed to connect to the database: {target_db}")
            log_action(user, "import_csv_to_raw_page_data", "Failed to connect to the database")
            return

        cursor = conn.cursor()

        # Check if the raw_page_data table exists
        cursor.execute("SHOW TABLES LIKE 'raw_page_data'")
        table_exists = cursor.fetchone()
        if not table_exists:
            print(f"Table 'raw_page_data' does not exist.")
            log_action(user, "import_csv_to_raw_page_data", f"Table 'raw_page_data' does not exist.")
            return

        # Find the newest CSV file in the directory
        files = [f for f in os.listdir(dir_path) if f.startswith("latest_pages_data_") and f.endswith(".csv")]
        if not files:
            print(f"No CSV file found in the directory {dir_path}")
            log_action(user, "import_csv_to_raw_page_data", f"No CSV file found in the directory {dir_path}")
            return

        full_paths = [os.path.join(dir_path, f) for f in files]
        file_path = max(full_paths, key=os.path.getctime)

        # Enable local infile globally
        cursor.execute("SET GLOBAL local_infile = 1;")

        # Load data from the CSV file into raw_page_data
        import_query = f"""
        LOAD DATA LOCAL INFILE '{file_path.replace("\\", "\\\\")}'
        INTO TABLE raw_page_data
        FIELDS TERMINATED BY ','
        ENCLOSED BY '\"'
        LINES TERMINATED BY '\\n'
        IGNORE 1 ROWS
        (latest_page_id, page_title, page_text, export_time)
        SET import_time = NOW();
        """

        cursor.execute(import_query)
        conn.commit()

        print(f"Data from {file_path} has been successfully imported into the raw_page_data table.")
        log_action(user, "import_csv_to_raw_page_data", f"Data from {file_path} imported successfully")

    except Error as e:
        print(f"Error: {e}")
        log_action(user, "import_csv_to_raw_page_data", f"Error: {e}")
    finally:
        if conn:
            close_connection(conn)

# Example usage
# import_csv_to_raw_page_data("username", "C:\\Users\\micha\\Downloads")


def copy_n_convert(user, source_table='raw_page_data', target_table='pages'):
    """Copy data from raw_page_data to pages, sanitize title and text, and set sum entry to empty string."""
    target_db = config['database']
    try:
        conn = create_connection(target_db)
        if not conn:
            print(f"Failed to connect to the database: {target_db}")
            log_action(user, "copy_n_convert", "Failed to connect to the database")
            return

        cursor = conn.cursor()

        # Check if the source table exists
        cursor.execute(f"SHOW TABLES LIKE '{source_table}'")
        source_exists = cursor.fetchone()
        if not source_exists:
            print(f"Source table '{source_table}' does not exist.")
            log_action(user, "copy_n_convert", f"Source table '{source_table}' does not exist.")
            return

        # Check if the target table exists
        cursor.execute(f"SHOW TABLES LIKE '{target_table}'")
        target_exists = cursor.fetchone()
        if not target_exists:
            print(f"Target table '{target_table}' does not exist.")
            log_action(user, "copy_n_convert", f"Target table '{target_table}' does not exist.")
            return

        # Truncate the target table to delete existing data
        cursor.execute(f"TRUNCATE TABLE {target_table}")

        # Fetch data from the source table (raw_page_data)
        cursor.execute(f"SELECT latest_page_id, page_title, page_text FROM {source_table}")
        rows = cursor.fetchall()

        base_url = get_mediawiki_base_url()

        if rows:
            for row in rows:
                page_id, page_title, page_text = row

                # Sanitize the title
                if isinstance(page_title, bytearray):
                    page_title = bytes(page_title).decode('utf-8')
                elif isinstance(page_title, bytes):
                    page_title = page_title.decode('utf-8')
                page_title = page_title.replace('_', ' ')

                # Sanitize the text
                if isinstance(page_text, bytearray):
                    page_text = bytes(page_text).decode('utf-8')
                elif isinstance(page_text, bytes):
                    page_text = page_text.decode('utf-8')
                page_text = parse_database_text(parse_wikitext_to_clean_text(page_text))

                # Construct the page link
                page_link = f"{base_url}index.php?title={page_title.replace(' ', '_')}"

                # Fetch summary text for the current page_id
                cursor.execute(f"SELECT sum_text FROM summaries WHERE page_id = %s ORDER BY sum_update_time DESC LIMIT 1", (page_id,))
                summary_result = cursor.fetchone()
                sum_text = summary_result[0] if summary_result else ''

                # Insert new entry into pages
                cursor.execute(f"""
                    INSERT INTO {target_table} (id, title, clean_text, sum_text, link)
                    VALUES (%s, %s, %s, %s, %s)
                """, (page_id, page_title, page_text, sum_text, page_link))

            conn.commit()
            print(f"Data copied and converted from {source_table} to {target_table} in {target_db}")
            log_action(user, "copy_n_convert", f"Data copied and sanitized from {source_table} to {target_table}")
        else:
            print(f"No data found in table {source_table}")

    except Error as e:
        print(f"Error: {e}")
        log_action(user, "error", str(e))
    finally:
        if conn:
            close_connection(conn)



