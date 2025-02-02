# URL Shortener Application
import os
import secrets
import string
from datetime import datetime, timedelta
from flask import Flask, redirect, render_template, request, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import validators
from werkzeug.exceptions import HTTPException
from colorama import init
init()

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(__name__)
app.config.update({
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///urls.db',
    'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    'SECRET_KEY': os.environ.get('SECRET_KEY') or secrets.token_hex(32),
    'BASE_URL': 'http://localhost:5000',
    'DEFAULT_EXPIRATION_DAYS': 30,
    'RATE_LIMIT': "100 per day;10 per minute"
})

# Initialize database
db = SQLAlchemy(app)

# Rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[app.config['RATE_LIMIT']]
)

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Database model
class ShortURL(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    original_url = db.Column(db.String(2048), nullable=False)
    short_code = db.Column(db.String(16), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    visit_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<ShortURL {self.original_url} -> {self.short_code}>'

# Create database tables
with app.app_context():
    db.create_all()

# Custom validators
def validate_url(url):
    if not validators.url(url):
        raise ValueError('Invalid URL format')
    return url

def generate_short_code(length=6):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

# Error handlers
@app.errorhandler(HTTPException)
def handle_exception(e):
    print(f"{Colors.FAIL}Error: {e.code} {e.name}{Colors.ENDC}")
    return render_template('error.html', error=e), e.code

# CLI Commands
@app.cli.command('cleanup')
def cleanup_expired_urls():
    """Remove expired URLs from database"""
    expired = ShortURL.query.filter(ShortURL.expires_at < datetime.utcnow()).all()
    for url in expired:
        db.session.delete(url)
    db.session.commit()
    print(f"{Colors.OKGREEN}Removed {len(expired)} expired URLs{Colors.ENDC}")

# Routes
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        return create_short_url()
    return render_template('index.html')

@app.route('/<short_code>')
def redirect_url(short_code):
    url = ShortURL.query.filter_by(short_code=short_code).first_or_404()
    
    if url.expires_at and url.expires_at < datetime.utcnow():
        db.session.delete(url)
        db.session.commit()
        return render_template('error.html', 
            error={'code': 410, 'description': 'URL Expired'}), 410
    
    url.visit_count += 1
    db.session.commit()
    
    return redirect(url.original_url)

@app.route('/stats/<short_code>')
def url_stats(short_code):
    url = ShortURL.query.filter_by(short_code=short_code).first_or_404()
    return render_template('stats.html', 
        url=url,
        short_url=f"{app.config['BASE_URL']}/{url.short_code}"
    )

@app.route('/api/shorten', methods=['POST'])
@limiter.limit("5 per minute")
def api_create_short_url():
    data = request.get_json()
    original_url = data.get('url')
    custom_code = data.get('custom_code')
    
    try:
        validate_url(original_url)
        short_code = create_short_url_entry(original_url, custom_code)
        return jsonify({
            'short_url': f"{app.config['BASE_URL']}/{short_code}",
            'original_url': original_url
        }), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

# Helper functions
def create_short_url():
    original_url = request.form['url']
    custom_code = request.form.get('custom_code')
    
    try:
        validate_url(original_url)
        short_code = create_short_url_entry(original_url, custom_code)
        return render_template('result.html',
            short_url=f"{app.config['BASE_URL']}/{short_code}",
            original_url=original_url
        )
    except ValueError as e:
        return render_template('index.html', error=str(e)), 400

def create_short_url_entry(original_url, custom_code=None):
    if custom_code:
        if ShortURL.query.filter_by(short_code=custom_code).first():
            raise ValueError('Custom code already in use')
        if not validators.slug(custom_code):
            raise ValueError('Invalid custom code')
        short_code = custom_code
    else:
        short_code = generate_short_code()
        while ShortURL.query.filter_by(short_code=short_code).first():
            short_code = generate_short_code()
    
    expiration = datetime.utcnow() + timedelta(
        days=app.config['DEFAULT_EXPIRATION_DAYS']
    )
    
    new_url = ShortURL(
        original_url=original_url,
        short_code=short_code,
        expires_at=expiration
    )
    
    db.session.add(new_url)
    db.session.commit()
    
    print(f"Created short URL: {short_code}")
    return short_code

# Start application
if __name__ == '__main__':
    print(f"{Colors.OKCYAN}Starting URL shortener...{Colors.ENDC}")
    app.run(debug=True)
