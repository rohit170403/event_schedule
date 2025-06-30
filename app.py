from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import threading
import time
import os
from sqlalchemy import or_

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///events.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email configuration (optional)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('EMAIL_USER')
app.config['MAIL_PASSWORD'] = os.environ.get('EMAIL_PASS')

db = SQLAlchemy(app)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    events = db.relationship('Event', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    is_recurring = db.Column(db.Boolean, default=False)
    recurrence_type = db.Column(db.String(20), nullable=True)  # daily, weekly, monthly
    recurrence_end = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reminder_sent = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat(),
            'is_recurring': self.is_recurring,
            'recurrence_type': self.recurrence_type,
            'recurrence_end': self.recurrence_end.isoformat() if self.recurrence_end else None,
            'created_at': self.created_at.isoformat(),
            'user_id': self.user_id
        }

    def __repr__(self):
        return f'<Event {self.title}>'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables
with app.app_context():
    db.create_all()

# Helper Functions
def generate_recurring_events(event):
    """Generate recurring event instances based on recurrence pattern"""
    events = []
    if not event.is_recurring or not event.recurrence_type:
        return events
    
    current_start = event.start_time
    current_end = event.end_time
    end_date = event.recurrence_end or (datetime.now() + timedelta(days=365))
    
    while current_start <= end_date:
        if event.recurrence_type == 'daily':
            current_start += timedelta(days=1)
            current_end += timedelta(days=1)
        elif event.recurrence_type == 'weekly':
            current_start += timedelta(weeks=1)
            current_end += timedelta(weeks=1)
        elif event.recurrence_type == 'monthly':
            current_start += timedelta(days=30)  # Simplified monthly
            current_end += timedelta(days=30)
        
        if current_start <= end_date:
            recurring_event = Event(
                title=f"{event.title} (Recurring)",
                description=event.description,
                start_time=current_start,
                end_time=current_end,
                is_recurring=False,  # Mark as non-recurring to avoid infinite loops
                user_id=event.user_id
            )
            events.append(recurring_event)
    
    return events

def send_reminder_email(event):
    """Send email reminder for an event"""
    try:
        # Email functionality commented out - uncomment and configure as needed
        print(f"Email reminder would be sent for: {event.title}")
        return True
    except Exception as e:
        print(f"Failed to send email reminder: {e}")
        return False

def check_reminders():
    """Background task to check for upcoming events and send reminders"""
    while True:
        try:
            with app.app_context():
                now = datetime.now()
                one_hour_later = now + timedelta(hours=1)
                
                # Find events starting within the next hour that haven't had reminders sent
                upcoming_events = Event.query.filter(
                    Event.start_time >= now,
                    Event.start_time <= one_hour_later,
                    Event.reminder_sent == False
                ).all()
                
                for event in upcoming_events:
                    print(f"Reminder: Event '{event.title}' starts at {event.start_time}")
                    send_reminder_email(event)
                    event.reminder_sent = True
                    db.session.commit()
                    
        except Exception as e:
            print(f"Error in reminder check: {e}")
        
        time.sleep(60)  # Check every minute

# Start reminder checker in background thread
reminder_thread = threading.Thread(target=check_reminders, daemon=True)
reminder_thread.start()

def is_time_slot_available(start_time, end_time, user_id, exclude_event_id=None):
    """Check if time slot is available for a specific user"""
    conflict_query = Event.query.filter(
        Event.user_id == user_id,
        Event.start_time < end_time,
        Event.end_time > start_time
    )
    if exclude_event_id:
        conflict_query = conflict_query.filter(Event.id != exclude_event_id)
    return conflict_query.first() is None

# Authentication Routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        # Validation
        if password != confirm_password:
            flash('Passwords do not match!', 'danger')
            return render_template('register.html')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'danger')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists!', 'danger')
            return render_template('register.html')
        
        # Create new user
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('Invalid username or password!', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Web Routes
@app.route('/')
@login_required
def index():
    events = Event.query.filter_by(user_id=current_user.id).order_by(Event.start_time).all()
    events_json = [event.to_dict() for event in events]
    return render_template('index.html', events=events, events_json=events_json)

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_event():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
        end_time = datetime.strptime(request.form['end_time'], '%Y-%m-%dT%H:%M')
        is_recurring = 'is_recurring' in request.form
        recurrence_type = request.form.get('recurrence_type') if is_recurring else None
        recurrence_end = None
        
        if is_recurring and request.form.get('recurrence_end'):
            recurrence_end = datetime.strptime(request.form['recurrence_end'], '%Y-%m-%d')
        
        # Check for time slot availability for current user
        if not is_time_slot_available(start_time, end_time, current_user.id):
            flash('Time slot conflicts with your existing event. Please choose a different time.', 'danger')
            return redirect(url_for('add_event'))
        
        event = Event(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            is_recurring=is_recurring,
            recurrence_type=recurrence_type,
            recurrence_end=recurrence_end,
            user_id=current_user.id
        )
        
        db.session.add(event)
        db.session.commit()
        
        # Generate recurring events if applicable
        if event.is_recurring:
            recurring_events = generate_recurring_events(event)
            for recurring_event in recurring_events:
                db.session.add(recurring_event)
            db.session.commit()
        
        flash('Event added successfully!', 'success')
        return redirect(url_for('index'))
    
    return render_template('add_event.html')

@app.route('/edit/<int:event_id>', methods=['GET', 'POST'])
@login_required
def edit_event(event_id):
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    
    if request.method == 'POST':
        event.title = request.form['title']
        event.description = request.form['description']
        new_start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
        new_end_time = datetime.strptime(request.form['end_time'], '%Y-%m-%dT%H:%M')
        
        # Check for time slot availability (excluding current event)
        if not is_time_slot_available(new_start_time, new_end_time, current_user.id, event_id):
            flash('Time slot conflicts with your existing event. Please choose a different time.', 'danger')
            return render_template('edit_event.html', event=event)
        
        event.start_time = new_start_time
        event.end_time = new_end_time
        event.is_recurring = 'is_recurring' in request.form
        event.recurrence_type = request.form.get('recurrence_type') if event.is_recurring else None
        
        if event.is_recurring and request.form.get('recurrence_end'):
            event.recurrence_end = datetime.strptime(request.form['recurrence_end'], '%Y-%m-%d')
        else:
            event.recurrence_end = None
        
        db.session.commit()
        flash('Event updated successfully!', 'success')
        return redirect(url_for('index'))
    
    return render_template('edit_event.html', event=event)

@app.route('/delete/<int:event_id>')
@login_required
def delete_event(event_id):
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    db.session.delete(event)
    db.session.commit()
    flash('Event deleted successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/search')
@login_required
def search_events():
    query = request.args.get('q', '')
    if query:
        events = Event.query.filter(
            Event.user_id == current_user.id,
            or_(Event.title.contains(query), Event.description.contains(query))
        ).order_by(Event.start_time).all()
    else:
        events = []
    return render_template('search.html', events=events, query=query)

# REST API Routes
@app.route('/api/events', methods=['GET'])
@login_required
def api_get_events():
    events = Event.query.filter_by(user_id=current_user.id).order_by(Event.start_time).all()
    return jsonify([event.to_dict() for event in events])

@app.route('/api/events', methods=['POST'])
@login_required
def api_create_event():
    data = request.get_json()
    
    try:
        start_time = datetime.fromisoformat(data['start_time'])
        end_time = datetime.fromisoformat(data['end_time'])
        
        # Check for time slot availability
        if not is_time_slot_available(start_time, end_time, current_user.id):
            return jsonify({'error': 'Time slot conflicts with existing event'}), 400
        
        event = Event(
            title=data['title'],
            description=data.get('description', ''),
            start_time=start_time,
            end_time=end_time,
            is_recurring=data.get('is_recurring', False),
            recurrence_type=data.get('recurrence_type'),
            recurrence_end=datetime.fromisoformat(data['recurrence_end']) if data.get('recurrence_end') else None,
            user_id=current_user.id
        )
        
        db.session.add(event)
        db.session.commit()
        
        # Generate recurring events if applicable
        if event.is_recurring:
            recurring_events = generate_recurring_events(event)
            for recurring_event in recurring_events:
                db.session.add(recurring_event)
            db.session.commit()
        
        return jsonify({'message': 'Event created successfully', 'event': event.to_dict()}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/events/<int:event_id>', methods=['GET'])
@login_required
def api_get_event(event_id):
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    return jsonify(event.to_dict())

@app.route('/api/events/<int:event_id>', methods=['PUT'])
@login_required
def api_update_event(event_id):
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    
    try:
        event.title = data.get('title', event.title)
        event.description = data.get('description', event.description)
        
        if 'start_time' in data:
            new_start_time = datetime.fromisoformat(data['start_time'])
            new_end_time = datetime.fromisoformat(data['end_time']) if 'end_time' in data else event.end_time
            
            # Check for time slot availability
            if not is_time_slot_available(new_start_time, new_end_time, current_user.id, event_id):
                return jsonify({'error': 'Time slot conflicts with existing event'}), 400
            
            event.start_time = new_start_time
        
        if 'end_time' in data:
            event.end_time = datetime.fromisoformat(data['end_time'])
        
        event.is_recurring = data.get('is_recurring', event.is_recurring)
        event.recurrence_type = data.get('recurrence_type', event.recurrence_type)
        
        if data.get('recurrence_end'):
            event.recurrence_end = datetime.fromisoformat(data['recurrence_end'])
        
        db.session.commit()
        return jsonify({'message': 'Event updated successfully', 'event': event.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/events/<int:event_id>', methods=['DELETE'])
@login_required
def api_delete_event(event_id):
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Event deleted successfully'})

@app.route('/api/events/search', methods=['GET'])
@login_required
def api_search_events():
    query = request.args.get('q', '')
    if query:
        events = Event.query.filter(
            Event.user_id == current_user.id,
            or_(Event.title.contains(query), Event.description.contains(query))
        ).order_by(Event.start_time).all()
        return jsonify([event.to_dict() for event in events])
    return jsonify([])

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
