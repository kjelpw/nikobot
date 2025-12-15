"""Flask web application for NikoBot monitoring"""
import os
from flask import Flask, render_template_string

app = Flask(__name__)


@app.route('/')
def index():
    """Home page"""
    return '<h1>NikoBot Web Interface</h1><p>Bot is running!</p><p><a href="/log">View Logs</a></p>'


@app.route('/log')
def view_log():
    """View recent log entries"""
    log_file = 'log.txt'
    num_lines = 50
    
    if not os.path.exists(log_file):
        return '<p>No log file found.</p><p><a href="/">Back to Home</a></p>'
    
    try:
        # Read the last N lines efficiently
        with open(log_file, 'r', encoding='utf-8') as f:
            # Read all lines and get the last N
            lines = f.readlines()
            recent_lines = lines[-num_lines:] if len(lines) > num_lines else lines
        
        # Create HTML output
        html_lines = ['<h1>Recent Log Entries</h1>']
        html_lines.append('<p><a href="/">Back to Home</a></p>')
        html_lines.append('<div style="font-family: monospace; white-space: pre-wrap;">')
        
        for line in recent_lines:
            html_lines.append(f'{line}<br>')
            
        html_lines.append('</div>')
        
        return ''.join(html_lines)
        
    except Exception as e:
        return f'<p>Error reading log file: {str(e)}</p><p><a href="/">Back to Home</a></p>'


@app.route('/health')
def health():
    """Health check endpoint"""
    return {'status': 'ok', 'service': 'nikobot-web'}


def main():
    """Run the Flask application"""
    app.run(host='0.0.0.0', port=5000, debug=False)


if __name__ == '__main__':
    main()
