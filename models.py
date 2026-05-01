from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'

    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name       = db.Column(db.String(255), nullable=False)
    avatar_url = db.Column(db.String(512), nullable=True)

    provider    = db.Column(db.String(50),  nullable=False)   # 'google'
    provider_id = db.Column(db.String(255), nullable=True, index=True)

    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id':         self.id,
            'email':      self.email,
            'name':       self.name,
            'avatar_url': self.avatar_url,
            'provider':   self.provider,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }

    def __repr__(self):
        return f'<User {self.email}>'
