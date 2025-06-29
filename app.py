from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message  
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
mail = Mail(app)

# Database Models
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
            'created_at': self.created_at.isoformat()
        }

    def __repr__(self):
        return f'<Event {self.title}>'

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
                is_recurring=False  # Mark as non-recurring to avoid infinite loops
            )
            events.append(recurring_event)
    
    return events

def send_reminder_email(event):
    """Send email reminder for an event"""
    try:
        msg = Message(
            subject=f'Event Reminder: {event.title}',
            sender=app.config['MAIL_USERNAME'],
            recipients=['user@example.com']  # Replace with actual recipient
        )
        msg.body = f'''
        Event Reminder: {event.title}
        
        Description: {event.description}
        Start Time: {event.start_time.strftime('%Y-%m-%d %H:%M')}
        End Time: {event.end_time.strftime('%Y-%m-%d %H:%M')}
        
        This event is starting soon!
        '''
        mail.send(msg)
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
                    # Uncomment the next line to enable email reminders
                    # send_reminder_email(event)
                    event.reminder_sent = True
                    db.session.commit()
                    
        except Exception as e:
            print(f"Error in reminder check: {e}")
        
        time.sleep(60)  # Check every minute

# Start reminder checker in background thread
reminder_thread = threading.Thread(target=check_reminders, daemon=True)
reminder_thread.start()

def is_time_slot_available(start_time, end_time, exclude_event_id=None):
    conflict_query = Event.query.filter(
        Event.start_time < end_time,
        Event.end_time > start_time
    )
    if exclude_event_id:
        conflict_query = conflict_query.filter(Event.id != exclude_event_id)
    return conflict_query.first() is None

# Web Routes
@app.route('/')
def index():
    events = Event.query.order_by(Event.start_time).all()
    events_json = [event.to_dict() for event in events]
    return render_template('index.html', events=events, events_json=events_json)



@app.route('/add', methods=['GET', 'POST'])
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
        
        event = Event(
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            is_recurring=is_recurring,
            recurrence_type=recurrence_type,
            recurrence_end=recurrence_end
        )
        
        # Check for time slot availability
        if not is_time_slot_available(start_time, end_time):
            flash('Time slot conflicts with an existing event. Please choose a different time.', 'danger')
            return redirect(url_for('add_event'))

        db.session.add(event)
        # Generate recurring events if applicable
        db.session.commit()
        flash('Event added successfully!', 'success')

        return redirect(url_for('index'))
    
    return render_template('add_event.html')

@app.route('/edit/<int:event_id>', methods=['GET', 'POST'])
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    
    if request.method == 'POST':
        event.title = request.form['title']
        event.description = request.form['description']
        event.start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M')
        event.end_time = datetime.strptime(request.form['end_time'], '%Y-%m-%dT%H:%M')
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
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash('Event deleted successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/search')
def search_events():
    query = request.args.get('q', '')
    if query:
        events = Event.query.filter(
            or_(Event.title.contains(query), Event.description.contains(query))
        ).order_by(Event.start_time).all()
    else:
        events = []
    return render_template('search.html', events=events, query=query)

# REST API Routes
@app.route('/api/events', methods=['GET'])
def api_get_events():
    events = Event.query.order_by(Event.start_time).all()
    return jsonify([event.to_dict() for event in events])

@app.route('/api/events', methods=['POST'])
def api_create_event():
    data = request.get_json()
    
    try:
        event = Event(
            title=data['title'],
            description=data.get('description', ''),
            start_time=datetime.fromisoformat(data['start_time']),
            end_time=datetime.fromisoformat(data['end_time']),
            is_recurring=data.get('is_recurring', False),
            recurrence_type=data.get('recurrence_type'),
            recurrence_end=datetime.fromisoformat(data['recurrence_end']) if data.get('recurrence_end') else None
        )
        
        db.session.add(event)
        
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
def api_get_event(event_id):
    event = Event.query.get_or_404(event_id)
    return jsonify(event.to_dict())

@app.route('/api/events/<int:event_id>', methods=['PUT'])
def api_update_event(event_id):
    event = Event.query.get_or_404(event_id)
    data = request.get_json()
    
    try:
        event.title = data.get('title', event.title)
        event.description = data.get('description', event.description)
        
        if 'start_time' in data:
            event.start_time = datetime.fromisoformat(data['start_time'])
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
def api_delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Event deleted successfully'})

@app.route('/api/events/search', methods=['GET'])
def api_search_events():
    query = request.args.get('q', '')
    if query:
        events = Event.query.filter(
            or_(Event.title.contains(query), Event.description.contains(query))
        ).order_by(Event.start_time).all()
        return jsonify([event.to_dict() for event in events])
    return jsonify([])

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
