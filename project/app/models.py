from datetime import datetime
from app import db


class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    series_code = db.Column(db.String(20), nullable=False)
    series_desc = db.Column(db.String(100), nullable=False)
    pallet_id = db.Column(db.String(20), nullable=False)
    pallet_available_flag = db.Column(db.Boolean, nullable=False)
    item_id = db.Column(db.String(20), nullable=False)
    item_desc = db.Column(db.String(100), nullable=False)
    family_code = db.Column(db.String(20), nullable=False)
    reporting_group_desc = db.Column(db.String(50), nullable=False)
    publisher_desc = db.Column(db.String(50), nullable=False)
    imprint_desc = db.Column(db.String(50), nullable=False)
    us_price = db.Column(db.Float)
    can_price = db.Column(db.Float)
    pub_date = db.Column(db.DateTime, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    extended_retail = db.Column(db.Float)
    extended_percent = db.Column(db.Float)

class UserFiles(db.Model):
    __tablename__ = 'user_files'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<UserFile {self.filename}>"