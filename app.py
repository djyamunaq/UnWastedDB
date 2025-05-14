from math import ceil
from flask import Flask, render_template, request, g, current_app, abort, send_from_directory
import sqlite3
import os
import pandas as pd

app = Flask(__name__)

CONTENT_FOLDER = os.path.join(app.root_path, 'data/samples/')
DATABASE = os.path.join(app.root_path, 'data/unwasted.db')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  

        # print(f"Successfully connected to database: {DATABASE}")

        # # Print the names of all tables
        # cursor = db.cursor()
        # cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        # tables = cursor.fetchall()
        # cursor.close()

        # print("\n--- Available Tables ---")
        # if tables:
        #     for table in tables:
        #         print(table['name'])  # Access table name by column name
        # else:
        #     print("No tables found in the database.")
        # print("--- End of Tables List ---")
        
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

@app.route('/')
def index():
    page_size = 100

    page = request.args.get('page')
    if page == None:
        page = 1
    page = int(page)

    visible_columns_str = request.args.get('visible_columns')
    filter_genomes_str = request.args.get('filter_genomes')

    offset = (page -1) * page_size

    visible_columns = []
    filter_genomes = []

    visible_columns = visible_columns_str.split(',') if visible_columns_str else ['run_accession', 'available_genomes']
    visible_columns.append('run_accession')
    visible_columns.append('available_genomes')

    filter_genomes = filter_genomes_str.split(',') if filter_genomes_str else []

    always_visible_columns = ['run_accession', 'available_genomes']

    columns = query_db(f"PRAGMA table_info('Entries');")
    columns_sorted = [c['name'] for c in columns if c['name'] != 'entry_id']
    columns_sorted = sorted(columns_sorted)

    where_clause = ""
    where_args = []

    if filter_genomes:
        placeholders = ','.join(['?'] * len(filter_genomes))
        where_clause = f"WHERE e.run_accession IN (SELECT DISTINCT gf.entry_id FROM GenomicFiles gf WHERE gf.genomic_type IN ({placeholders}))"
        where_args.extend(filter_genomes)

    query = f"""
        SELECT DISTINCT e.*
        FROM Entries e
        {where_clause}
        LIMIT {page_size}
        OFFSET {offset}
    """

    genomic_types = query_db("SELECT genomic_type FROM GenomicFiles;")
    genomic_types = [g['genomic_type'] for g in genomic_types]
    genomic_types = list(set(genomic_types))

    # entries_data_rows = query_db("SELECT * FROM Entries;")
    entries_data_rows = query_db(query, where_args)
    # Convert sqlite3.Row objects to a list of dictionaries
    entries_data = [dict(row) for row in entries_data_rows]

    query = f"""
        SELECT COUNT(*)
        FROM Entries e
        {where_clause}
    """
    total_count = query_db(query, where_args)
    total_count = total_count[0][0]
    total_pages = ceil(total_count/page_size) 

    columns_names = [' '.join(c['name'].split('_')).upper() for c in columns]

    visible_columns_names = [' '.join(vc.split('_')).upper() for vc in visible_columns]

    return render_template('index.html', table_name="Entries", columns_sorted=columns_sorted, columns=columns, data=entries_data, always_visible_columns=always_visible_columns, visible_columns=visible_columns, genomic_types=genomic_types, filter_genomes=filter_genomes, current_page=page, total_pages=total_pages, has_next=(total_pages > page), has_prev=(page > 1), columns_names=columns_names, visible_columns_names=visible_columns_names)

@app.route('/content/<path:filename>',methods=['GET'])
def get_content_file(filename):
    return send_from_directory(CONTENT_FOLDER, filename)


@app.route('/apply_advanced_filter', methods=['POST'])
def apply_advanced_filter():
    return {}


@app.route('/entry/<run_accession>')
def show_entry(run_accession):
    entry_data = query_db("SELECT * FROM Entries WHERE run_accession = ?", (run_accession,), one=True)
    columns = query_db(f"PRAGMA table_info('Entries');")
    columns = [c['name'] for c in columns]
    
    if entry_data:
        entry_data = {columns[i]: entry_data[i] for i in range(len(entry_data))}

        entry_data = dict(sorted(entry_data.items()))

        aux_files = query_db("SELECT * FROM AuxFiles WHERE entry_id = ?", (run_accession,))
        columns = query_db(f"PRAGMA table_info('AuxFiles');")
        columns = [c['name'] for c in columns]
        aux_files = [{columns[j]: aux_files[i][columns[j]] for j in range(len(columns))} for i in range(len(aux_files))]

        final_result = [a['file_path'] for a in aux_files if 'final-results.txt' in a['file_path']][0]

        filename = '/'.join(final_result.split('/')[-2:])
        file_path = os.path.join(CONTENT_FOLDER, filename)

        try:
            with open(file_path) as f:
                file_content = f.read()
        except FileNotFoundError:
            file_content = 'File not found!'

        genomic_files = query_db("SELECT * FROM GenomicFiles WHERE entry_id = ?", (run_accession,))
        columns = query_db(f"PRAGMA table_info('GenomicFiles');")
        columns = [c['name'] for c in columns]

        genomic_files = [{columns[j]: genomic_files[i][columns[j]] for j in range(len(columns))} for i in range(len(genomic_files))]

        for i in range(len(genomic_files)): 
            genomic_files[i]['file_path'] = '/'.join(genomic_files[i]['file_path'].split('/')[-2:]) 
            genomic_files[i]['file_id'] = genomic_files[i]['entry_id'] + '/' + genomic_files[i]['genomic_type']
            del genomic_files[i]['entry_id']

        return render_template('entry_details.html', entry=entry_data, final_result=file_content, final_result_path=filename, genomic_files=genomic_files)
    else:
        return "Entry not found."
    
@app.route('/download/<path:file_identifier>')
def download_file_route(file_identifier: str):
    """
    Serves a file from the configured GENOMIC_FILES_DIRECTORY for download.
    The 'file_identifier' is expected to be the filename or a relative path
    within that directory.
    """
    # download_dir = current_app.config.get('GENOMIC_FILES_DIRECTORY')
    download_dir = CONTENT_FOLDER

    if not download_dir:
        current_app.logger.error("GENOMIC_FILES_DIRECTORY not configured.")
        abort(500) # Internal Server Error

    try:
        # send_from_directory is secure against directory traversal
        # as_attachment=True sets Content-Disposition header for download
        return send_from_directory(
            directory=download_dir,
            path=file_identifier,
            as_attachment=True
            # download_name="custom_filename.ext" # Optional: force a specific download name
        )
    except FileNotFoundError:
        current_app.logger.error(f"File not found: {file_identifier} in {download_dir}")
        abort(404) # Not Found
    except Exception as e:
        current_app.logger.error(f"Error sending file {file_identifier}: {e}")
        abort(500) # Internal Server Error

@app.route('/query', methods=['POST'])
def execute_query():
    query = request.form['query']
    try:
        results = query_db(query)
        columns = []
        if results:
            columns = results[0].keys()
        return render_template('display_table.html', table_name="Custom Query", columns=columns, data=results)
    except sqlite3.Error as e:
        return render_template('display_table.html', table_name="Error", error=str(e))


if __name__ == '__main__':
    app.run(debug=True)