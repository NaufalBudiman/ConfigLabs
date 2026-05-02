from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name       = db.Column(db.String(255), nullable=False)
    avatar_url = db.Column(db.String(512), nullable=True)
    provider    = db.Column(db.String(50),  nullable=False)
    provider_id = db.Column(db.String(255), nullable=True, index=True)
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    saved_files = db.relationship('SavedFile', backref='user', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {'id':self.id,'email':self.email,'name':self.name,'avatar_url':self.avatar_url,'provider':self.provider,'created_at':self.created_at.isoformat(),'last_login':self.last_login.isoformat() if self.last_login else None}

class SavedFile(db.Model):
    __tablename__ = 'saved_files'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name         = db.Column(db.String(255), nullable=False)
    file_type    = db.Column(db.String(50),  nullable=False)   # 'config' | 'topology'
    data         = db.Column(db.Text, nullable=False)           # JSON string
    vendor       = db.Column(db.String(50),  nullable=True)
    hostname     = db.Column(db.String(255), nullable=True)
    device_count = db.Column(db.Integer,     nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {'id':self.id,'name':self.name,'file_type':self.file_type,'vendor':self.vendor,'hostname':self.hostname,'device_count':self.device_count,'created_at':self.created_at.isoformat(),'updated_at':self.updated_at.isoformat()}

    def to_dict_full(self):
        d = self.to_dict()
        d['data'] = json.loads(self.data)
        return d
