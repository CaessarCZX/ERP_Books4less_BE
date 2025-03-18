from flask import Blueprint, jsonify, render_template
from .models import Inventory
from . import db

bp = Blueprint('routes', __name__)

@bp.route('/items', methods=['GET'])
def get_items():
    items = Inventory.query.all()
    return jsonify([{
        'id': item.id,
        'series_code': item.series_code,
        'series_desc': item.series_desc,
        'pallet_id': item.pallet_id,
        'pallet_available_flag': item.pallet_available_flag,
        'item_id': item.item_id,
        'item_desc': item.item_desc,
        'family_code': item.family_code,
        'reporting_group_desc': item.reporting_group_desc,
        'publisher_desc': item.publisher_desc,
        'imprint_desc': item.imprint_desc,
        'us_price': item.us_price,
        'can_price': item.can_price,
        'pub_date': item.pub_date.strftime('%Y-%m-%d'),
        'quantity': item.quantity,
        'extended_retail': item.extended_retail,
        'extended_percent': item.extended_percent
    } for item in items])

@bp.route('/')
def index():
    return render_template('index.html')

def init_app(app):
    app.register_blueprint(bp)
